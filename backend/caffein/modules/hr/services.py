# SPDX-License-Identifier: AGPL-3.0-or-later
"""Services des RH pour les autres modules (Projets, Production, Maintenance…).

Les autres modules n'accèdent aux salariés et aux absences que par ces fonctions, et seulement si les RH sont
actives (`core.modules.is_enabled("hr")`) ou déclarées dans leurs dépendances.
"""

from __future__ import annotations

from datetime import date

from ... import db
from ...utils import parse_date, today
from .entities import leave_taken
from .workdays import is_working_day, public_holidays, working_days  # noqa: F401 (pour les autres modules)


def employee(employee_id: int | None) -> dict | None:
    if not employee_id:
        return None
    return db.fetch_one("SELECT id, code, full_name, first_name, last_name, email, department_id, job_title, active "
                        "FROM hr_employees WHERE id = ?", (employee_id,))


def absent_employee_ids(day: date | str | None = None) -> set[int]:
    """Salariés en absence validée ce jour-là (aujourd'hui par défaut)."""
    when = (parse_date(day) or today()).isoformat()
    return {r["employee_id"] for r in db.fetch_all(
        "SELECT DISTINCT employee_id FROM hr_absences WHERE status = 'approved' AND start_date <= ? AND end_date >= ?",
        (when, when))}


def is_absent(employee_id: int, day: date | str | None = None) -> bool:
    return employee_id in absent_employee_ids(day)


def leave_balance(employee_id: int, year: int | None = None) -> float | None:
    """Solde de congés payés d'une année civile (l'année en cours par défaut), en jours ouvrés :
    congés annuels moins congés payés validés. None si le salarié n'existe pas."""
    row = db.fetch_one("SELECT annual_leave_days FROM hr_employees WHERE id = ?", (employee_id,))
    if row is None:
        return None
    taken = leave_taken([employee_id], year or today().year).get(employee_id, 0)
    return round((row["annual_leave_days"] or 0) - taken, 2)
