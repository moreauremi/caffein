# SPDX-License-Identifier: AGPL-3.0-or-later
"""RH : services, salariés, absences et congés, notes de frais."""

from __future__ import annotations

from ... import db
from ...core.modules import Kpi, Module, Page, Shortcut
from ...utils import today
from .demo import seed_demo
from .entities import ENTITIES, MIGRATIONS


def _headcount() -> dict:
    n = db.fetch_one("SELECT COUNT(*) AS n FROM hr_employees WHERE active = 1")["n"]
    return {"value": n, "count": n}


def _absent_today() -> dict:
    day = today().isoformat()
    n = db.fetch_one("SELECT COUNT(DISTINCT employee_id) AS n FROM hr_absences WHERE status = 'approved' "
                     "AND start_date <= ? AND end_date >= ?", (day, day))["n"]
    return {"value": n, "count": n}


def _to_approve() -> dict:
    """Demandes d'absence et notes de frais qui attendent une décision."""
    absences = db.fetch_one("SELECT COUNT(*) AS n FROM hr_absences WHERE status = 'requested'")["n"]
    expenses = db.fetch_one("SELECT COUNT(*) AS n FROM hr_expenses WHERE status = 'submitted'")["n"]
    return {"value": absences + expenses, "count": absences + expenses}


MODULE = Module(
    key="hr", slug="rh", label=("RH", "HR"),
    description=("Services, salariés, absences et congés (jours ouvrés et soldes calculés), notes de frais.",
                 "Departments, employees, absences and leave (working days and balances calculated), expense reports."),
    icon="Users", order=20,
    migrations=MIGRATIONS, entities=ENTITIES,
    pages=[
        Page("salaries", ("Salariés", "Employees"), entity="hr.employees", icon="IdCard"),
        Page("absences", ("Absences", "Absences"), entity="hr.absences", icon="CalendarOff"),
        Page("notes-de-frais", ("Notes de frais", "Expense reports"), entity="hr.expenses", icon="Receipt"),
        Page("services", ("Services", "Departments"), entity="hr.departments", icon="Network"),
    ],
    # Libellés précis : « Mes vues » retient un chiffre clé quand la demande cite tout son libellé
    kpis=[
        Kpi("headcount", ("Effectif salarié", "Employee headcount"), _headcount, icon="Users",
            foot=("salarié(s) actif(s)", "active employee(s)"), path="/rh/salaries?f_active=1"),
        Kpi("absent_today", ("Salariés absents aujourd'hui", "Employees absent today"), _absent_today, icon="CalendarOff",
            foot=("absence(s) validée(s) en cours", "approved absence(s) in progress"), path="/rh/absences?f_status=approved"),
        Kpi("to_approve", ("Demandes RH à valider", "HR requests to approve"), _to_approve, icon="ClipboardCheck",
            foot=("demandes d'absence et notes de frais", "absence requests and expense reports"),
            path="/rh/absences?f_status=requested", alert=lambda d: (d.get("value") or 0) > 0),
    ],
    shortcuts=[Shortcut("new_absence", ("Demande d'absence", "Absence request"), "/rh/absences?new=1", icon="CalendarDays")],
    seed_demo=seed_demo,
    reset_tables=("hr_expense_lines", "hr_expenses", "hr_absences", "hr_employees", "hr_departments"),
)
