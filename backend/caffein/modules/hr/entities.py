# SPDX-License-Identifier: AGPL-3.0-or-later
"""RH : services, salariés, absences et congés, notes de frais.

Les autres modules désignent un salarié par `hr.employees` (champs `full_name`, `email`, `department_id`).
Tout est calculé ici, en Python : ancienneté, jours ouvrés (hors week-ends et jours fériés), congés validés et
solde de l'année, effectif des services, totaux des notes de frais. Le salaire est une donnée sensible :
visible et modifiable seulement au niveau « gestion ».
"""

from __future__ import annotations

from datetime import date

from ... import db, services
from ...core import modules as registry
from ...core.entities import Action, Child, Entity, Field
from ...core.errors import Conflict, Forbidden
from ...core.modules import MANAGE
from ...core.permissions import level_for
from ...utils import fmt_date, fmt_money, parse_date, today
from .workdays import working_days

MIGRATIONS = [
    (1, """
-- Services. manager_id : le salarié responsable (même module : clé étrangère permise)
CREATE TABLE IF NOT EXISTS hr_departments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL DEFAULT '',
    manager_id INTEGER REFERENCES hr_employees(id) ON DELETE SET NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_hr_departments_name ON hr_departments(name COLLATE NOCASE);

-- Salariés. full_name (« Prénom Nom ») est tenu à jour à chaque enregistrement ; salary est sensible.
CREATE TABLE IF NOT EXISTS hr_employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL DEFAULT '',
    first_name TEXT NOT NULL DEFAULT '',
    last_name TEXT NOT NULL DEFAULT '',
    full_name TEXT NOT NULL DEFAULT '',
    department_id INTEGER REFERENCES hr_departments(id) ON DELETE RESTRICT,
    job_title TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    hire_date TEXT,
    end_date TEXT,
    contract_type TEXT NOT NULL DEFAULT 'cdi'
        CHECK (contract_type IN ('cdi', 'cdd', 'apprentice', 'intern', 'temp', 'freelance')),
    weekly_hours REAL,
    annual_leave_days REAL,
    salary REAL,
    active INTEGER NOT NULL DEFAULT 1,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_hr_employees_code ON hr_employees(code) WHERE code != '';
CREATE INDEX IF NOT EXISTS idx_hr_employees_department ON hr_employees(department_id);

-- Absences : demandes et décisions. Les jours ouvrés ne sont pas stockés : ils se calculent depuis les dates.
CREATE TABLE IF NOT EXISTS hr_absences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL DEFAULT '',
    employee_id INTEGER REFERENCES hr_employees(id) ON DELETE RESTRICT,
    kind TEXT NOT NULL DEFAULT 'paid_leave'
        CHECK (kind IN ('paid_leave', 'rtt', 'sick', 'unpaid', 'training', 'other')),
    start_date TEXT,
    end_date TEXT,
    status TEXT NOT NULL DEFAULT 'requested' CHECK (status IN ('requested', 'approved', 'refused', 'cancelled')),
    reason TEXT NOT NULL DEFAULT '',
    decided_on TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_hr_absences_code ON hr_absences(code) WHERE code != '';
CREATE INDEX IF NOT EXISTS idx_hr_absences_employee ON hr_absences(employee_id, start_date);
CREATE INDEX IF NOT EXISTS idx_hr_absences_status ON hr_absences(status);

-- Notes de frais et leurs dépenses (montants TTC, dont TVA)
CREATE TABLE IF NOT EXISTS hr_expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL DEFAULT '',
    employee_id INTEGER REFERENCES hr_employees(id) ON DELETE RESTRICT,
    title TEXT NOT NULL DEFAULT '',
    date TEXT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'submitted', 'approved', 'refused', 'paid')),
    paid_on TEXT,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_hr_expenses_code ON hr_expenses(code) WHERE code != '';
CREATE INDEX IF NOT EXISTS idx_hr_expenses_employee ON hr_expenses(employee_id);
CREATE INDEX IF NOT EXISTS idx_hr_expenses_status ON hr_expenses(status);

CREATE TABLE IF NOT EXISTS hr_expense_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_id INTEGER NOT NULL REFERENCES hr_expenses(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    date TEXT,
    category TEXT NOT NULL DEFAULT 'other'
        CHECK (category IN ('transport', 'meals', 'lodging', 'mileage', 'supplies', 'other')),
    description TEXT NOT NULL DEFAULT '',
    amount REAL,
    vat REAL
);
CREATE INDEX IF NOT EXISTS idx_hr_expense_lines_expense ON hr_expense_lines(expense_id, position);
"""),
]

CONTRACTS = (
    ("cdi", ("CDI", "Permanent")), ("cdd", ("CDD", "Fixed-term")), ("apprentice", ("Alternance", "Apprenticeship")),
    ("intern", ("Stage", "Internship")), ("temp", ("Intérim", "Temporary")), ("freelance", ("Indépendant", "Freelance")),
)
ABSENCE_KINDS = (
    ("paid_leave", ("Congés payés", "Paid leave"), "accent"), ("rtt", ("RTT", "Time off in lieu")),
    ("sick", ("Maladie", "Sick leave"), "warn"), ("unpaid", ("Sans solde", "Unpaid leave")),
    ("training", ("Formation", "Training"), "info"), ("other", ("Autre", "Other")),
)
ABSENCE_STATUSES = (
    ("requested", ("Demandée", "Requested"), "info"), ("approved", ("Validée", "Approved"), "good"),
    ("refused", ("Refusée", "Refused"), "bad"), ("cancelled", ("Annulée", "Cancelled"), "outline"),
)
EXPENSE_STATUSES = (
    ("draft", ("Brouillon", "Draft")), ("submitted", ("Soumise", "Submitted"), "info"),
    ("approved", ("Validée", "Approved"), "accent"), ("refused", ("Refusée", "Refused"), "bad"),
    ("paid", ("Remboursée", "Paid"), "good"),
)
EXPENSE_CATEGORIES = (
    ("transport", ("Transport", "Transport")), ("meals", ("Repas", "Meals")), ("lodging", ("Hébergement", "Lodging")),
    ("mileage", ("Indemnités kilométriques", "Mileage allowance")), ("supplies", ("Fournitures", "Supplies")),
    ("other", ("Autre", "Other")),
)


def _today() -> str:
    return today().isoformat()


def _marks(ids: list) -> str:
    return ", ".join("?" for _ in ids)


def _days_text(value: float | None) -> str:
    """Nombre de jours pour un message : 5.0 → « 5 », 2.5 → « 2,5 »."""
    return f"{round(value or 0, 2):g}".replace(".", ",")


# ═════════════════════════════════════════════════════════════════════════
# Congés payés : jours validés et solde par année civile
# ═════════════════════════════════════════════════════════════════════════
def leave_taken(employee_ids: list[int], year: int, exclude_id: int | None = None) -> dict[int, int]:
    """Jours ouvrés de congés payés validés de chaque salarié dans l'année civile `year`. Une absence à cheval
    sur deux années ne compte que ses jours de l'année."""
    ids = sorted({i for i in employee_ids if i})
    if not ids:
        return {}
    first, last = date(year, 1, 1), date(year, 12, 31)
    rows = db.fetch_all(
        f"SELECT employee_id, start_date, end_date FROM hr_absences WHERE kind = 'paid_leave' AND status = 'approved' "
        f"AND employee_id IN ({_marks(ids)}) AND start_date <= ? AND end_date >= ? AND id != ?",
        (*ids, last.isoformat(), first.isoformat(), exclude_id or 0))
    taken: dict[int, int] = {}
    for row in rows:
        start, end = parse_date(row["start_date"]), parse_date(row["end_date"])
        if start is None or end is None:
            continue
        taken[row["employee_id"]] = taken.get(row["employee_id"], 0) + working_days(max(start, first), min(end, last))
    return taken


def check_balance(employee_id: int | None, start: date, end: date, exclude_id: int | None = None) -> None:
    """Congés payés demandés : pour chaque année civile de la période, pas plus de jours que le solde restant."""
    row = db.fetch_one("SELECT annual_leave_days FROM hr_employees WHERE id = ?", (employee_id,))
    allowance = (row or {}).get("annual_leave_days") or 0
    for year in range(start.year, end.year + 1):
        wanted = working_days(max(start, date(year, 1, 1)), min(end, date(year, 12, 31)))
        remaining = allowance - leave_taken([employee_id], year, exclude_id).get(employee_id, 0)
        if wanted and wanted > remaining + 1e-9:
            where = f" en {year}" if start.year != end.year else ""
            raise ValueError(f"Solde de congés insuffisant : il reste {_days_text(max(remaining, 0))} jour(s){where}.")


# ═════════════════════════════════════════════════════════════════════════
# Services
# ═════════════════════════════════════════════════════════════════════════
def _department_headcount(rows: list[dict]) -> None:
    """Effectif : salariés actifs rattachés au service (une requête groupée pour toute la liste)."""
    ids = [r["id"] for r in rows if r.get("id")]
    counts = {}
    if ids:
        counts = {r["department_id"]: r["n"] for r in db.fetch_all(
            f"SELECT department_id, COUNT(*) AS n FROM hr_employees WHERE active = 1 AND department_id IN ({_marks(ids)}) "
            f"GROUP BY department_id", tuple(ids))}
    for row in rows:
        row["headcount"] = counts.get(row.get("id"), 0)


DEPARTMENTS = Entity(
    module="hr", name="departments", table="hr_departments", label=("Service", "Department"),
    plural=("Services", "Departments"), title="name", order_by="name COLLATE NOCASE", icon="Network",
    description=("Les services de l'entreprise, leur responsable et leur effectif.",
                 "The company's departments, their manager and their headcount."),
    fields=[
        Field("name", ("Nom", "Name"), required=True, unique=True, list=True, search=True, maxlength=80),
        Field("manager_id", ("Responsable", "Manager"), type="ref", ref="hr.employees", list=True),
        Field("headcount", ("Effectif", "Headcount"), type="int", computed=True, list=True),
        Field("description", ("Description", "Description"), type="longtext", width="full"),
    ],
    compute=_department_headcount,
)


# ═════════════════════════════════════════════════════════════════════════
# Salariés
# ═════════════════════════════════════════════════════════════════════════
def _employee_prepare(values: dict, existing: dict | None) -> None:
    """Nom complet « Prénom Nom », recalculé à chaque enregistrement (il suit un changement de nom)."""
    first = values.get("first_name", (existing or {}).get("first_name")) or ""
    last = values.get("last_name", (existing or {}).get("last_name")) or ""
    values["full_name"] = f"{first} {last}".strip()


def _employee_validate(values: dict, existing: dict | None) -> None:
    hired, left = parse_date(values.get("hire_date")), parse_date(values.get("end_date"))
    if hired and left and left < hired:
        raise ValueError("Date de sortie : elle ne peut pas précéder la date d'entrée.")


def _employee_figures(rows: list[dict]) -> None:
    """Ancienneté (jusqu'à aujourd'hui, ou jusqu'à la date de sortie si elle est passée), congés payés validés
    dans l'année civile en cours et solde. Une requête groupée pour toute la liste."""
    ref = today()
    taken = leave_taken([r.get("id") for r in rows], ref.year)
    for row in rows:
        hired, left = parse_date(row.get("hire_date")), parse_date(row.get("end_date"))
        if hired is None:
            row["seniority_years"] = None
        else:
            until = min(ref, left) if left else ref
            row["seniority_years"] = round(max((until - hired).days, 0) / 365.25, 1)
        row["leave_taken"] = taken.get(row.get("id"), 0)
        row["leave_balance"] = round((row.get("annual_leave_days") or 0) - row["leave_taken"], 2)


EMPLOYEES = Entity(
    module="hr", name="employees", table="hr_employees", label=("Salarié", "Employee"), plural=("Salariés", "Employees"),
    title="full_name", subtitle="job_title", order_by="last_name COLLATE NOCASE, first_name COLLATE NOCASE", icon="IdCard",
    active="active",
    description=("Contrats, services, ancienneté et congés calculés. Les salaires ne sont visibles qu'au niveau gestion.",
                 "Contracts, departments, calculated seniority and leave. Salaries are only visible at manage level."),
    fields=[
        Field("code", ("Matricule", "Staff number"), type="code", prefix="MAT", yearly=False, readonly=True, list=True,
              search=True),
        Field("first_name", ("Prénom", "First name"), required=True, search=True, maxlength=80),
        Field("last_name", ("Nom", "Last name"), required=True, search=True, maxlength=80),
        Field("full_name", ("Nom complet", "Full name"), readonly=True, list=True, search=True),
        Field("department_id", ("Service", "Department"), type="ref", ref="hr.departments", list=True, filter=True),
        Field("job_title", ("Poste", "Job title"), list=True, search=True, maxlength=120),
        Field("email", ("Email", "Email"), type="email", search=True),
        Field("phone", ("Téléphone", "Phone"), type="phone"),
        Field("hire_date", ("Date d'entrée", "Hire date"), type="date", list=True),
        Field("end_date", ("Date de sortie", "Leaving date"), type="date",
              help=("Fin du contrat ou départ du salarié.", "End of the contract or the employee's leaving date.")),
        Field("contract_type", ("Contrat", "Contract"), type="enum", choices=CONTRACTS, default="cdi", required=True,
              list=True, filter=True),
        Field("weekly_hours", ("Heures par semaine", "Weekly hours"), type="decimal", default=35, min=0, max=60),
        Field("annual_leave_days", ("Congés annuels (jours)", "Annual leave (days)"), type="decimal", default=25, min=0,
              max=60, help=("Jours ouvrés de congés payés par année civile (25 pour un temps plein).",
                            "Working days of paid leave per calendar year (25 for a full-time job).")),
        Field("salary", ("Salaire brut mensuel", "Gross monthly salary"), type="money", min=0, max=1_000_000, sensitive=True),
        Field("seniority_years", ("Ancienneté (années)", "Seniority (years)"), type="decimal", computed=True,
              help=("Depuis la date d'entrée, jusqu'à la date de sortie si elle est passée.",
                    "From the hire date, up to the leaving date once it has passed.")),
        Field("leave_taken", ("Congés validés cette année (jours)", "Approved leave this year (days)"), type="decimal",
              computed=True),
        Field("leave_balance", ("Solde de congés (jours)", "Leave balance (days)"), type="decimal", computed=True, list=True),
        Field("active", ("Actif", "Active"), type="bool", default=True, filter=True),
        Field("notes", ("Notes", "Notes"), type="longtext", width="full"),
    ],
    prepare=_employee_prepare, validate=_employee_validate, compute=_employee_figures,
)


# ═════════════════════════════════════════════════════════════════════════
# Absences
# ═════════════════════════════════════════════════════════════════════════
def _absence_days(rows: list[dict]) -> None:
    """Jours ouvrés de la période : du lundi au vendredi, dates incluses, hors jours fériés."""
    for row in rows:
        row["days"] = working_days(row.get("start_date"), row.get("end_date"))


def _absence_validate(values: dict, existing: dict | None) -> None:
    start, end = parse_date(values.get("start_date")), parse_date(values.get("end_date"))
    if start is None or end is None:
        return  # dates obligatoires : déjà signalées
    if end < start:
        raise ValueError("Date de fin : elle ne peut pas précéder la date de début.")
    if not working_days(start, end):
        raise ValueError("Date de début : la période ne compte aucun jour ouvré (week-end ou jour férié).")
    own_id = (existing or {}).get("id") or 0
    other = db.fetch_one(
        "SELECT start_date, end_date FROM hr_absences WHERE employee_id = ? AND id != ? AND status IN ('requested', 'approved') "
        "AND start_date <= ? AND end_date >= ? ORDER BY start_date LIMIT 1",
        (values.get("employee_id"), own_id, end.isoformat(), start.isoformat()))
    if other:
        raise ValueError(f"Date de début : la période chevauche une autre absence du salarié "
                         f"(du {fmt_date(other['start_date'])} au {fmt_date(other['end_date'])}).")
    if values.get("kind") == "paid_leave":
        check_balance(values.get("employee_id"), start, end, own_id)


ABSENCE_LOCKS = {
    "approved": "Absence validée : elle ne se modifie plus. Annulez-la puis faites une nouvelle demande si besoin.",
    "refused": "Demande refusée : elle ne se modifie plus.",
    "cancelled": "Absence annulée : elle ne se modifie plus.",
}


def _absence_locked(row: dict) -> str | None:
    return ABSENCE_LOCKS.get(row.get("status"))


def _absence_before_delete(row: dict) -> None:
    if row.get("status") != "requested":
        raise Conflict("Seule une demande d'absence en attente peut être supprimée.")


def _set_absence(absence_id: int, status: str, **extra) -> None:
    db.update("hr_absences", absence_id, {"status": status, "updated_at": db.now_iso(), **extra})


def _approve_absence(row: dict, payload: dict, user: dict) -> str:
    if row["kind"] == "paid_leave":  # d'autres congés ont pu être validés depuis la demande
        check_balance(row["employee_id"], parse_date(row["start_date"]), parse_date(row["end_date"]), row["id"])
    _set_absence(row["id"], "approved", decided_on=_today())
    return f"Absence {row['code']} validée : {_days_text(row['days'])} jour(s) ouvré(s)."


def _refuse_absence(row: dict, payload: dict, user: dict) -> str:
    _set_absence(row["id"], "refused", decided_on=_today())
    return f"Demande d'absence {row['code']} refusée."


def _cancel_absence(row: dict, payload: dict, user: dict) -> str:
    # Une absence validée et déjà commencée appartient à l'historique (congés décomptés) : la gestion seule l'annule
    started = row["status"] == "approved" and (row.get("start_date") or "") <= _today()
    level = user["module_level"] if "module_level" in user else level_for(user, "hr")
    if started and level < MANAGE:
        raise Forbidden("Cette absence validée a déjà commencé : seul un responsable (niveau gestion) peut l'annuler.")
    _set_absence(row["id"], "cancelled")
    return f"Absence {row['code']} annulée."


ABSENCES = Entity(
    module="hr", name="absences", table="hr_absences", label=("Absence", "Absence"), plural=("Absences", "Absences"),
    title="code", order_by="start_date DESC, id DESC", icon="CalendarOff", board="status",
    description=("Congés, RTT, maladie, formation : les demandes et leur validation. Les jours ouvrés excluent les "
                 "week-ends et les jours fériés.",
                 "Leave, time off, sick leave, training: requests and approvals. Working days exclude weekends and "
                 "public holidays."),
    fields=[
        Field("code", ("Numéro", "Number"), type="code", prefix="ABS", readonly=True, search=True),
        Field("employee_id", ("Salarié", "Employee"), type="ref", ref="hr.employees", required=True, list=True, filter=True),
        Field("kind", ("Type", "Type"), type="enum", choices=ABSENCE_KINDS, default="paid_leave", required=True, list=True,
              filter=True),
        Field("start_date", ("Date de début", "Start date"), type="date", default=_today, required=True, list=True),
        Field("end_date", ("Date de fin", "End date"), type="date", required=True, list=True,
              help=("Dernier jour d'absence, inclus.", "Last day of absence, included.")),
        Field("days", ("Jours ouvrés", "Working days"), type="decimal", computed=True, list=True),
        Field("status", ("Statut", "Status"), type="enum", choices=ABSENCE_STATUSES, default="requested", readonly=True,
              list=True, filter=True),
        Field("reason", ("Motif", "Reason"), maxlength=300, width="full"),
        Field("decided_on", ("Date de décision", "Decision date"), type="date", readonly=True),
    ],
    actions=[
        Action("approve", ("Valider", "Approve"), _approve_absence, when=lambda r: r["status"] == "requested", level=MANAGE,
               style="primary", icon="CalendarCheck"),
        Action("refuse", ("Refuser", "Refuse"), _refuse_absence, when=lambda r: r["status"] == "requested", level=MANAGE,
               style="danger", icon="Ban", confirm=("Refuser cette demande d'absence ?", "Refuse this absence request?")),
        Action("cancel", ("Annuler", "Cancel"), _cancel_absence, when=lambda r: r["status"] in ("requested", "approved"),
               style="danger", icon="X", confirm=("Annuler cette absence ?", "Cancel this absence?")),
    ],
    compute=_absence_days, validate=_absence_validate, locked=_absence_locked, before_delete=_absence_before_delete,
)


# ═════════════════════════════════════════════════════════════════════════
# Notes de frais
# ═════════════════════════════════════════════════════════════════════════
def _expense_totals(rows: list[dict]) -> None:
    """Total TTC et TVA : depuis les dépenses de la fiche (fiche, saisie en cours), sinon par une requête groupée (liste)."""
    missing = [r["id"] for r in rows if "lines" not in r and r.get("id")]
    lines_by_expense: dict[int, list[dict]] = {}
    if missing:
        for line in db.fetch_all(f"SELECT expense_id, amount, vat FROM hr_expense_lines WHERE expense_id IN ({_marks(missing)})",
                                 tuple(missing)):
            lines_by_expense.setdefault(line["expense_id"], []).append(line)
    for row in rows:
        lines = (row.get("lines") or []) if "lines" in row else lines_by_expense.get(row.get("id"), [])
        row["total"] = round(sum(line.get("amount") or 0 for line in lines), 2)
        row["total_vat"] = round(sum(line.get("vat") or 0 for line in lines), 2)


def _expense_validate(values: dict, existing: dict | None) -> None:
    for i, line in enumerate(values.get("lines") or [], start=1):
        vat = line.get("vat") or 0
        if vat > (line.get("amount") or 0):
            raise ValueError(f"Dépenses, ligne {i} — Dont TVA : elle ne peut pas dépasser le montant TTC.")
        if vat and line.get("category") == "mileage":
            raise ValueError(f"Dépenses, ligne {i} — Dont TVA : les indemnités kilométriques ne comportent pas de TVA.")


EXPENSE_LOCKS = {
    "submitted": "Note de frais soumise : elle ne se modifie plus pendant sa validation.",
    "approved": "Note de frais validée : elle ne se modifie plus.",
    "refused": "Note de frais refusée : elle ne se modifie plus. Créez-en une nouvelle si besoin.",
    "paid": "Note de frais remboursée : elle ne se modifie plus.",
}


def _expense_locked(row: dict) -> str | None:
    return EXPENSE_LOCKS.get(row.get("status"))


def _expense_before_delete(row: dict) -> None:
    if row.get("status") != "draft":
        raise Conflict("Seule une note de frais en brouillon peut être supprimée.")


def _set_expense(expense_id: int, status: str, **extra) -> None:
    db.update("hr_expenses", expense_id, {"status": status, "updated_at": db.now_iso(), **extra})


def _submit(row: dict, payload: dict, user: dict) -> str:
    if not row.get("lines"):
        raise ValueError("Dépenses : ajoutez au moins une dépense avant de soumettre la note de frais.")
    if not row.get("total"):
        raise ValueError("Dépenses : le total de la note de frais est nul, il n'y a rien à rembourser.")
    _set_expense(row["id"], "submitted")
    return f"Note de frais {row['code']} soumise pour validation."


def _approve_expense(row: dict, payload: dict, user: dict) -> str:
    _set_expense(row["id"], "approved")
    return f"Note de frais {row['code']} validée : elle peut être remboursée."


def _refuse_expense(row: dict, payload: dict, user: dict) -> str:
    _set_expense(row["id"], "refused")
    return f"Note de frais {row['code']} refusée."


def _pay(row: dict, payload: dict, user: dict) -> str:
    paid_on = _today()
    total, vat = row["total"], row["total_vat"]
    message = f"Note de frais {row['code']} remboursée ({fmt_money(total)})."
    # La Comptabilité, si elle est active, reçoit la dépense comme justificatif (TVA déductible)
    if registry.is_enabled("accounting"):
        employee = db.fetch_one("SELECT full_name FROM hr_employees WHERE id = ?", (row["employee_id"],))
        services.add_document({
            "date": paid_on, "fournisseur": f"NOTE DE FRAIS {((employee or {}).get('full_name') or '').upper()}".strip(),
            "ht": round(total - vat, 2), "tva": vat, "ttc": total, "categorie": "Frais de déplacement",
            "resume": (row.get("title") or "")[:50], "tva_type": "deductible", "source": "expense", "extracted_by": "caffein",
        })
        message += f" Justificatif ajouté à la comptabilité (TVA déductible : {fmt_money(vat)})."
    _set_expense(row["id"], "paid", paid_on=paid_on)
    return message


EXPENSE_LINE_FIELDS = [
    Field("date", ("Date", "Date"), type="date", required=True),
    Field("category", ("Catégorie", "Category"), type="enum", choices=EXPENSE_CATEGORIES, default="other", required=True),
    Field("description", ("Description", "Description"), required=True, maxlength=200, width="full"),
    Field("amount", ("Montant TTC", "Amount incl. VAT"), type="money", required=True, min=0, max=1_000_000),
    Field("vat", ("Dont TVA", "Of which VAT"), type="money", default=0, min=0, max=1_000_000),
]

EXPENSES = Entity(
    module="hr", name="expenses", table="hr_expenses", label=("Note de frais", "Expense report"),
    plural=("Notes de frais", "Expense reports"), title="code", subtitle="title", order_by="date DESC, id DESC", icon="Receipt",
    board="status",
    description=("Les dépenses avancées par les salariés : soumission, validation et remboursement. Une fois remboursée, "
                 "la note rejoint les justificatifs de la Comptabilité, si elle est active.",
                 "Expenses paid by employees: submission, approval and refund. Once paid, the report joins the "
                 "accounting receipts when Accounting is on."),
    fields=[
        Field("code", ("Numéro", "Number"), type="code", prefix="NDF", readonly=True, list=True, search=True),
        Field("employee_id", ("Salarié", "Employee"), type="ref", ref="hr.employees", required=True, list=True, filter=True),
        Field("title", ("Objet", "Purpose"), required=True, list=True, search=True, maxlength=120),
        Field("date", ("Date", "Date"), type="date", default=_today, list=True),
        Field("status", ("Statut", "Status"), type="enum", choices=EXPENSE_STATUSES, default="draft", readonly=True, list=True,
              filter=True),
        Field("total", ("Total TTC", "Total incl. VAT"), type="money", computed=True, list=True),
        Field("total_vat", ("Dont TVA", "Of which VAT"), type="money", computed=True),
        Field("paid_on", ("Remboursée le", "Paid on"), type="date", readonly=True),
        Field("notes", ("Notes", "Notes"), type="longtext", width="full"),
    ],
    children=[Child("lines", ("Dépenses", "Expenses"), "hr_expense_lines", "expense_id", EXPENSE_LINE_FIELDS)],
    actions=[
        Action("submit", ("Soumettre", "Submit"), _submit, when=lambda r: r["status"] == "draft", style="primary", icon="Send"),
        Action("approve", ("Valider", "Approve"), _approve_expense, when=lambda r: r["status"] == "submitted", level=MANAGE,
               style="primary", icon="BadgeCheck"),
        Action("refuse", ("Refuser", "Refuse"), _refuse_expense, when=lambda r: r["status"] == "submitted", level=MANAGE,
               style="danger", icon="Ban", confirm=("Refuser cette note de frais ?", "Refuse this expense report?")),
        Action("pay", ("Rembourser", "Mark as paid"), _pay, when=lambda r: r["status"] == "approved", level=MANAGE,
               style="primary", icon="Banknote",
               confirm=("Marquer cette note de frais comme remboursée ?", "Mark this expense report as paid?")),
    ],
    compute=_expense_totals, validate=_expense_validate, locked=_expense_locked, before_delete=_expense_before_delete,
)

ENTITIES = [EMPLOYEES, ABSENCES, EXPENSES, DEPARTMENTS]
