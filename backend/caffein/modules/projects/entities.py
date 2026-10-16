# SPDX-License-Identifier: AGPL-3.0-or-later
"""Entités des Projets : projets, tâches et temps passés.

Un projet regroupe des tâches et le temps passé par l'équipe. Ses chiffres (heures passées, avancement par rapport au
budget en heures, heures restantes, tâches ouvertes, temps et montant à facturer) viennent de figures.py : ils ne sont
jamais stockés. « Facturer les temps » crée une facture brouillon dans les Ventes, une ligne par tâche, et y rattache les
temps repris : ils ne se modifient plus. Si la facture brouillon est supprimée, ou la facture annulée, ces temps
redeviennent à facturer.

Le client (Ventes) et les salariés (RH) sont des références facultatives : sans ces modules, les champs disparaissent
et les projets fonctionnent quand même.
"""

from __future__ import annotations

from ... import db, services
from ...core import modules as registry
from ...core.entities import Action, Entity, Field
from ...core.errors import Conflict, Forbidden
from ...core.modules import NONE, WRITE
from ...core.permissions import level_for
from ...utils import cents, fmt_date, fmt_money, today
from . import figures

MIGRATIONS = [
    (1, """
-- client_id : client des Ventes ; manager_id : salarié des RH (pas de clé étrangère vers un autre module)
CREATE TABLE IF NOT EXISTS projects_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    client_id INTEGER,
    manager_id INTEGER,
    status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'active', 'on_hold', 'done', 'cancelled')),
    start_date TEXT,
    end_date TEXT,
    budget_hours REAL,
    budget_amount REAL,
    hourly_rate REAL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_projects_code ON projects_projects(code) WHERE code != '';
CREATE INDEX IF NOT EXISTS idx_projects_projects_status ON projects_projects(status);
CREATE INDEX IF NOT EXISTS idx_projects_projects_client ON projects_projects(client_id);
CREATE INDEX IF NOT EXISTS idx_projects_projects_manager ON projects_projects(manager_id);

-- Tâches d'un projet. assignee_id : salarié des RH (pas de clé étrangère vers un autre module)
CREATE TABLE IF NOT EXISTS projects_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects_projects(id) ON DELETE RESTRICT,
    title TEXT NOT NULL DEFAULT '',
    assignee_id INTEGER,
    status TEXT NOT NULL DEFAULT 'todo' CHECK (status IN ('todo', 'in_progress', 'done')),
    priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    due_date TEXT,
    estimate_hours REAL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_projects_tasks_project ON projects_tasks(project_id, status);
CREATE INDEX IF NOT EXISTS idx_projects_tasks_assignee ON projects_tasks(assignee_id);

-- Temps passés. employee_id : salarié des RH ; invoice_id : facture des Ventes qui a repris le temps, billed_rate : le
-- taux horaire de cette facture (pas de clé étrangère vers un autre module)
CREATE TABLE IF NOT EXISTS projects_timesheets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT,
    project_id INTEGER REFERENCES projects_projects(id) ON DELETE RESTRICT,
    task_id INTEGER REFERENCES projects_tasks(id) ON DELETE RESTRICT,
    employee_id INTEGER,
    hours REAL,
    description TEXT NOT NULL DEFAULT '',
    billable INTEGER NOT NULL DEFAULT 1,
    invoice_id INTEGER,
    billed_rate REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_projects_timesheets_project ON projects_timesheets(project_id, date);
CREATE INDEX IF NOT EXISTS idx_projects_timesheets_task ON projects_timesheets(task_id);
CREATE INDEX IF NOT EXISTS idx_projects_timesheets_employee ON projects_timesheets(employee_id, date);
CREATE INDEX IF NOT EXISTS idx_projects_timesheets_date ON projects_timesheets(date);
CREATE INDEX IF NOT EXISTS idx_projects_timesheets_invoice ON projects_timesheets(invoice_id);
"""),
]

PROJECT_STATUSES = (
    ("planned", ("Prévu", "Planned")), ("active", ("En cours", "Active"), "info"),
    ("on_hold", ("En pause", "On hold"), "warn"), ("done", ("Terminé", "Completed"), "good"),
    ("cancelled", ("Annulé", "Cancelled"), "outline"),
)
TASK_STATUSES = (
    ("todo", ("À faire", "To do")), ("in_progress", ("En cours", "In progress"), "info"), ("done", ("Terminée", "Done"), "good"),
)
PRIORITIES = (
    ("low", ("Basse", "Low"), "outline"), ("normal", ("Normale", "Normal")), ("high", ("Haute", "High"), "warn"),
    ("urgent", ("Urgente", "Urgent"), "bad"),
)
MAX_DAY_HOURS = 24
INVOICED = "Temps déjà facturé : il ne se modifie plus."


def _today() -> str:
    return today().isoformat()


def _project_status(project_id: int | None) -> str | None:
    row = db.fetch_one("SELECT status FROM projects_projects WHERE id = ?", (project_id,)) if project_id else None
    return row["status"] if row else None


# ═════════════════════════════════════════════════════════════════════════
# Projets
# ═════════════════════════════════════════════════════════════════════════
def _project_figures(rows: list[dict]) -> None:
    """Heures passées, avancement, heures restantes, tâches ouvertes, temps et montant à facturer : trois requêtes
    groupées pour toute la liste. Le montant suit le taux de la fiche (celui en cours de saisie dans l'aperçu)."""
    ids = [r.get("id") for r in rows]
    spent = figures.hours_by("project_id", ids)
    tasks = figures.open_tasks(ids)
    unbilled = figures.billing_lines(figures.unbilled_entries(ids))
    for row in rows:
        row_id = row.get("id")
        hours_spent = spent.get(row_id, 0.0)
        budget = row.get("budget_hours")
        lines = unbilled.get(row_id, [])
        row["hours_spent"] = hours_spent
        row["progress"] = figures.percent(hours_spent, budget)
        row["remaining_hours"] = figures.hours(budget - hours_spent) if budget is not None else None
        row["tasks_open"] = tasks.get(row_id, 0)
        row["to_invoice_hours"] = figures.hours(sum(line["hours"] for line in lines))
        row["to_invoice_amount"] = figures.amount(lines, row.get("hourly_rate"))


def _project_validate(values: dict, existing: dict | None) -> None:
    start, end = values.get("start_date"), values.get("end_date")
    if start and end and end < start:
        raise ValueError("Date de fin : elle ne peut pas précéder la date de début.")


def _sales_level(user: dict) -> int:
    """Niveau de l'utilisateur sur les Ventes. Un appel interne (sans utilisateur : démonstration, script) agit
    avec le niveau qu'il a demandé."""
    if user.get("id") is None:
        return user.get("module_level", NONE)
    return level_for(user, "sales")


def _period(lines: list[dict]) -> tuple[str, str | None]:
    """Période des temps facturés, pour les notes de la facture, et dernier jour (date d'exécution de la prestation)."""
    dates = sorted(day for line in lines for day in (line["first_date"], line["last_date"]) if day)
    if not dates:
        return "Temps passés", None
    first, last = dates[0], dates[-1]
    if first == last:
        return f"Temps passé le {fmt_date(first)}", last
    return f"Temps passés du {fmt_date(first)} au {fmt_date(last)}", last


def _invoice_time(row: dict, payload: dict, user: dict) -> str:
    """Crée une facture brouillon des Ventes avec le temps à facturer du projet (une ligne par tâche, au taux horaire
    du projet) et y rattache les temps repris. La facture se vérifie puis s'émet dans les Ventes."""
    if not registry.is_enabled("sales"):
        raise ValueError("Ventes : le module est désactivé ; un administrateur peut l'activer dans Paramètres → Modules "
                         "pour facturer les temps.")
    if _sales_level(user) < WRITE:
        raise Forbidden("Ventes : il faut le droit d'écriture sur ce module pour créer la facture.")
    client_id = row.get("client_id")
    if not client_id:
        raise ValueError("Client : choisissez le client du projet avant de facturer les temps.")
    if not db.fetch_one("SELECT 1 FROM clients WHERE id = ?", (client_id,)):
        raise ValueError("Client : fiche introuvable ; choisissez un autre client pour le projet.")
    rate = row.get("hourly_rate")
    if not rate or rate <= 0:
        raise ValueError("Taux horaire facturé : renseignez un taux supérieur à zéro avant de facturer les temps.")
    entries = figures.unbilled_entries([row["id"]])
    lines = figures.billing_lines(entries).get(row["id"], [])
    if not lines:
        raise Conflict("Il n'y a plus de temps à facturer sur ce projet : rechargez-le.")
    period, last = _period(lines)
    invoice = services.create_invoice({
        "kind": "invoice", "client_id": client_id, "title": f"Projet {row['name']}",
        "items": [{"description": figures.line_description(line), "quantity": line["hours"], "unit_price": rate}
                  for line in lines],
        "delivery_date": last,
        "notes": f"{period} (projet {row['code']}).",
    })
    ids = [entry["id"] for entry in entries]
    try:
        # Les temps ne sont rattachés que s'ils sont toujours à facturer : deux facturations simultanées (double clic,
        # deux personnes) ne reprennent jamais deux fois le même temps
        with db.connect() as conn:
            cur = conn.execute(
                f"UPDATE projects_timesheets SET invoice_id = ?, billed_rate = ?, updated_at = ? "
                f"WHERE id IN ({', '.join('?' for _ in ids)}) AND project_id = ? AND billable = 1 "
                f"AND {figures.open_condition('projects_timesheets.invoice_id')}",
                (invoice["id"], cents(rate), db.now_iso(), *ids, row["id"]))
            if cur.rowcount != len(ids):
                raise Conflict("Les temps du projet viennent d'être modifiés ou facturés par ailleurs : rechargez le projet.")
    except Exception:
        services.delete_invoice(invoice["id"])  # rien n'a été rattaché : la facture brouillon disparaît
        raise
    total_hours = figures.hours(sum(line["hours"] for line in lines))
    return (f"Facture brouillon créée : {figures.hours_text(total_hours)} h pour {fmt_money(invoice['subtotal'])} HT. "
            "Vérifiez-la puis émettez-la dans Ventes, Factures et devis.")


PROJECTS = Entity(
    module="projects", name="projects", table="projects_projects", label=("Projet", "Project"), plural=("Projets", "Projects"),
    title="name", subtitle="code", order_by="id DESC", icon="FolderKanban", board="status",
    description=("Vos projets clients : budget, tâches, temps passés et avancement calculés ; les temps facturables "
                 "deviennent une facture brouillon en un clic.",
                 "Your customer projects: budget, tasks, time spent and progress calculated; billable time becomes a "
                 "draft invoice in one click."),
    fields=[
        Field("code", ("Numéro", "Number"), type="code", prefix="PRJ", readonly=True, list=True, search=True),
        Field("name", ("Nom du projet", "Project name"), required=True, list=True, search=True, maxlength=120),
        Field("client_id", ("Client", "Customer"), type="ref", ref="sales.clients", list=True, filter=True),
        Field("manager_id", ("Chef de projet", "Project manager"), type="ref", ref="hr.employees", filter=True),
        Field("status", ("Statut", "Status"), type="enum", choices=PROJECT_STATUSES, default="planned", required=True,
              list=True, filter=True),
        Field("start_date", ("Date de début", "Start date"), type="date"),
        Field("end_date", ("Date de fin", "End date"), type="date", list=True),
        Field("budget_hours", ("Budget en heures", "Budgeted hours"), type="decimal", min=0, max=100_000),
        Field("budget_amount", ("Budget HT", "Budget excl. VAT"), type="money", min=0, max=1_000_000_000),
        Field("hourly_rate", ("Taux horaire facturé", "Billed hourly rate"), type="money", default=65, min=0, max=100_000,
              help=("Prix HT d'une heure facturée au client.", "Price excl. VAT of an hour billed to the customer.")),
        Field("hours_spent", ("Heures passées", "Hours spent"), type="decimal", computed=True, list=True),
        Field("progress", ("Avancement", "Progress"), type="percent", computed=True, list=True,
              help=("Heures passées rapportées au budget en heures.", "Hours spent against the budgeted hours.")),
        Field("remaining_hours", ("Heures restantes", "Remaining hours"), type="decimal", computed=True,
              help=("Budget en heures moins heures passées ; négatif en cas de dépassement.",
                    "Budgeted hours minus hours spent; negative when over budget.")),
        Field("tasks_open", ("Tâches ouvertes", "Open tasks"), type="int", computed=True),
        Field("to_invoice_hours", ("Heures à facturer", "Hours to invoice"), type="decimal", computed=True,
              help=("Temps facturables pas encore facturés.", "Billable time not invoiced yet.")),
        Field("to_invoice_amount", ("Montant à facturer HT", "Amount to invoice excl. VAT"), type="money", computed=True,
              list=True, help=("Heures à facturer × taux horaire, une ligne par tâche comme sur la facture.",
                               "Hours to invoice × hourly rate, one line per task as on the invoice.")),
        Field("description", ("Description", "Description"), type="longtext", width="full"),
    ],
    actions=[
        Action("invoice_time", ("Facturer les temps", "Invoice time"), _invoice_time,
               when=lambda r: (r.get("to_invoice_hours") or 0) > 0, style="primary", icon="ReceiptText",
               confirm=("Créer une facture brouillon avec le temps à facturer ? Les temps facturés ne se modifieront plus.",
                        "Create a draft invoice with the time to invoice? Invoiced time can no longer be edited.")),
    ],
    compute=_project_figures, validate=_project_validate,
)


# ═════════════════════════════════════════════════════════════════════════
# Tâches
# ═════════════════════════════════════════════════════════════════════════
def _task_figures(rows: list[dict]) -> None:
    """Heures passées (une requête groupée pour toute la liste) ; en retard : pas terminée et échéance passée."""
    spent = figures.hours_by("task_id", [r.get("id") for r in rows])
    day = _today()
    for row in rows:
        due = row.get("due_date")
        row["spent_hours"] = spent.get(row.get("id"), 0.0)
        row["overdue"] = bool(due) and row.get("status") != "done" and str(due) < day


def _task_validate(values: dict, existing: dict | None) -> None:
    project_id = values.get("project_id")
    if existing is not None and project_id == existing.get("project_id"):
        return
    if existing is not None and db.fetch_one("SELECT 1 FROM projects_timesheets WHERE task_id = ? LIMIT 1", (existing["id"],)):
        raise ValueError("Projet : du temps est déjà saisi sur cette tâche ; elle ne peut plus changer de projet.")
    if _project_status(project_id) == "cancelled":
        raise ValueError("Projet : ce projet est annulé, on n'y ajoute plus de tâche.")


def _set_task_status(row: dict, status: str, origins: tuple[str, ...]) -> None:
    """Change le statut, seulement depuis l'un des statuts `origins` : deux actions simultanées sur la même tâche
    (double clic, deux personnes) ne passent pas toutes les deux."""
    with db.connect() as conn:
        cur = conn.execute(f"UPDATE projects_tasks SET status = ?, updated_at = ? WHERE id = ? "
                           f"AND status IN ({', '.join('?' for _ in origins)})", (status, db.now_iso(), row["id"], *origins))
        if cur.rowcount == 0:
            raise Conflict("La tâche vient d'être modifiée par ailleurs : rechargez-la.")


def _start(row: dict, payload: dict, user: dict) -> str:
    _set_task_status(row, "in_progress", ("todo",))
    return f"Tâche « {row['title']} » démarrée."


def _finish(row: dict, payload: dict, user: dict) -> str:
    _set_task_status(row, "done", ("todo", "in_progress"))
    return f"Tâche « {row['title']} » terminée."


TASKS = Entity(
    module="projects", name="tasks", table="projects_tasks", label=("Tâche", "Task"), plural=("Tâches", "Tasks"),
    title="title", order_by="due_date IS NULL, due_date, id DESC", icon="ListTodo", board="status",
    description=("Les tâches des projets : responsable, échéance, priorité, temps estimé et temps passé.",
                 "Project tasks: assignee, due date, priority, estimated time and time spent."),
    fields=[
        Field("title", ("Intitulé", "Title"), required=True, list=True, search=True, maxlength=200),
        Field("project_id", ("Projet", "Project"), type="ref", ref="projects.projects", required=True, list=True,
              filter=True),
        Field("assignee_id", ("Attribuée à", "Assigned to"), type="ref", ref="hr.employees", list=True, filter=True),
        Field("status", ("Statut", "Status"), type="enum", choices=TASK_STATUSES, default="todo", required=True, list=True,
              filter=True),
        Field("priority", ("Priorité", "Priority"), type="enum", choices=PRIORITIES, default="normal", required=True,
              list=True, filter=True),
        Field("due_date", ("Échéance", "Due date"), type="date", list=True),
        Field("estimate_hours", ("Temps estimé (heures)", "Estimated time (hours)"), type="decimal", min=0, max=100_000),
        Field("spent_hours", ("Heures passées", "Hours spent"), type="decimal", computed=True, list=True),
        Field("overdue", ("En retard", "Overdue"), type="bool", computed=True, list=True,
              help=("Pas terminée et échéance dépassée.", "Not done and past its due date.")),
        Field("description", ("Description", "Description"), type="longtext", width="full"),
    ],
    actions=[
        Action("start", ("Démarrer", "Start"), _start, when=lambda r: r["status"] == "todo", icon="Play"),
        Action("finish", ("Terminer", "Mark as done"), _finish, when=lambda r: r["status"] in ("todo", "in_progress"),
               style="primary", icon="CircleCheck"),
    ],
    compute=_task_figures, validate=_task_validate,
)


# ═════════════════════════════════════════════════════════════════════════
# Temps passés
# ═════════════════════════════════════════════════════════════════════════
def _timesheet_figures(rows: list[dict]) -> None:
    """Facturé : rattaché à une facture qui existe toujours et n'est pas annulée. Montant HT : heures × taux horaire
    du projet (le taux de la facture une fois facturé), zéro pour un temps non facturable. Une requête pour les taux
    et une pour les factures de toute la liste."""
    rates = figures.project_rates([r.get("project_id") for r in rows])
    invoices = figures.invoice_states([r.get("invoice_id") for r in rows])
    for row in rows:
        state = invoices.get(row.get("invoice_id"))
        invoiced = bool(state and state["valid"])
        row["invoiced"] = invoiced
        row["invoice_number"] = state["number"] if invoiced else ""
        billable = True if row.get("billable") is None else bool(row["billable"])  # une saisie neuve est facturable
        rate = row["billed_rate"] if invoiced and row.get("billed_rate") is not None else rates.get(row.get("project_id"))
        spent = row.get("hours")
        row["amount"] = cents(figures.hours(spent) * rate) if billable and rate and spent and spent > 0 else 0.0


def _timesheet_prepare(values: dict, existing: dict | None) -> None:
    """Heures au centième, la moitié vers le haut (1,005 → 1,01) : le montant et la facture suivent la même valeur."""
    if values.get("hours") is not None:
        values["hours"] = figures.hours(values["hours"])


def _timesheet_validate(values: dict, existing: dict | None) -> None:
    spent = values.get("hours")
    if spent is not None and spent <= 0:
        raise ValueError("Heures : elles doivent être supérieures à zéro.")
    project_id = values.get("project_id")
    if (existing is None or project_id != existing.get("project_id")) and _project_status(project_id) == "cancelled":
        raise ValueError("Projet : ce projet est annulé, on n'y saisit plus de temps.")
    task_id = values.get("task_id")
    if task_id:
        task = db.fetch_one("SELECT project_id FROM projects_tasks WHERE id = ?", (task_id,))
        if task is not None and task["project_id"] != project_id:
            raise ValueError("Tâche : elle n'appartient pas à ce projet.")
    employee_id, day = values.get("employee_id"), values.get("date")
    if employee_id and day and spent:
        other = db.fetch_one("SELECT COALESCE(SUM(hours), 0) AS h FROM projects_timesheets WHERE employee_id = ? AND date = ? "
                             "AND id != ?", (employee_id, day, (existing or {}).get("id") or 0))["h"]
        if other and figures.hours(other + spent) > MAX_DAY_HOURS:
            raise ValueError(f"Heures : le salarié a déjà {figures.hours_text(other)} h saisies ce jour-là ; une journée "
                             f"ne peut pas dépasser {MAX_DAY_HOURS} h.")


def _timesheet_locked(row: dict) -> str | None:
    return INVOICED if row.get("invoiced") else None


def _timesheet_before_delete(row: dict) -> None:
    if row.get("invoiced"):
        raise Conflict("Temps déjà facturé : il ne peut pas être supprimé.")


TIMESHEETS = Entity(
    module="projects", name="timesheets", table="projects_timesheets", label=("Temps passé", "Time entry"),
    plural=("Temps passés", "Time entries"), title="description", order_by="date DESC, id DESC", icon="Timer",
    description=("Le temps passé par l'équipe sur les projets, facturable ou non. Un temps facturé ne se modifie plus.",
                 "Time spent by the team on projects, billable or not. Invoiced time can no longer be edited."),
    fields=[
        Field("date", ("Date", "Date"), type="date", default=_today, required=True, list=True),
        Field("project_id", ("Projet", "Project"), type="ref", ref="projects.projects", required=True, list=True,
              filter=True),
        Field("task_id", ("Tâche", "Task"), type="ref", ref="projects.tasks", filter=True,
              help=("Facultative ; une tâche du projet choisi.", "Optional; a task of the chosen project.")),
        Field("employee_id", ("Salarié", "Employee"), type="ref", ref="hr.employees", list=True, filter=True),
        Field("hours", ("Heures", "Hours"), type="decimal", required=True, max=MAX_DAY_HOURS, list=True,
              help=("Durée en heures : 1,5 pour une heure trente.", "Duration in hours: 1.5 for an hour and a half.")),
        Field("description", ("Description", "Description"), list=True, search=True, maxlength=300, width="full"),
        Field("billable", ("Facturable", "Billable"), type="bool", default=True, list=True, filter=True),
        Field("amount", ("Montant HT", "Amount excl. VAT"), type="money", computed=True, list=True,
              help=("Heures × taux horaire du projet ; zéro si le temps n'est pas facturable.",
                    "Hours × the project's hourly rate; zero when the time is not billable.")),
        Field("invoiced", ("Facturé", "Invoiced"), type="bool", computed=True, list=True),
        Field("invoice_number", ("Facture", "Invoice"), computed=True),
        Field("invoice_id", ("Facture (identifiant)", "Invoice (id)"), type="int", readonly=True, hidden=True),
        Field("billed_rate", ("Taux facturé", "Billed rate"), type="money", readonly=True, hidden=True),
    ],
    compute=_timesheet_figures, prepare=_timesheet_prepare, validate=_timesheet_validate,
    locked=_timesheet_locked, before_delete=_timesheet_before_delete,
)

ENTITIES = [PROJECTS, TASKS, TIMESHEETS]
