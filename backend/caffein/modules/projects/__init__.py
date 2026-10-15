# SPDX-License-Identifier: AGPL-3.0-or-later
"""Projets : projets clients, tâches, temps passés et facturation des temps.

« Facturer les temps » crée une facture brouillon dans les Ventes (si elles sont actives) avec le temps facturable pas
encore facturé du projet, une ligne par tâche. Le client (Ventes) et les salariés (RH) sont des références facultatives :
le module fonctionne sans ces modules."""

from __future__ import annotations

from ... import db
from ...core.modules import Kpi, Module, Page, Shortcut
from ...utils import add_months, today
from . import figures
from .demo import seed_demo
from .entities import ENTITIES, MIGRATIONS


def _active_projects() -> dict:
    """Projets en cours, et leurs tâches pas encore terminées."""
    n = db.fetch_one("SELECT COUNT(*) AS n FROM projects_projects WHERE status = 'active'")["n"]
    tasks = db.fetch_one("SELECT COUNT(*) AS n FROM projects_tasks t JOIN projects_projects p ON p.id = t.project_id "
                         "WHERE p.status = 'active' AND t.status != 'done'")["n"]
    return {"value": n, "count": tasks}


def _hours_month() -> dict:
    """Heures saisies datées de ce mois-ci (facturables ou non), et nombre de temps saisis."""
    start = today().replace(day=1)
    total, entries = figures.hours_between(start, add_months(start, 1))
    return {"value": total, "count": entries}


def _time_to_invoice() -> dict:
    """Montant HT du temps facturable pas encore facturé, tous projets confondus, et nombre de projets concernés."""
    summary = figures.to_invoice_summary()
    return {"value": summary["amount"], "count": summary["projects"]}


MODULE = Module(
    key="projects", slug="projets", label=("Projets", "Projects"),
    description=("Projets clients, tâches et temps passés : avancement et budget calculés, temps facturables repris "
                 "dans une facture brouillon en un clic.",
                 "Customer projects, tasks and time entries: progress and budget calculated, billable time turned into "
                 "a draft invoice in one click."),
    icon="FolderKanban", order=70,
    migrations=MIGRATIONS, entities=ENTITIES,
    pages=[
        Page("projets", ("Projets", "Projects"), entity="projects.projects", icon="FolderKanban"),
        Page("taches", ("Tâches", "Tasks"), entity="projects.tasks", icon="ListTodo"),
        Page("temps", ("Temps passés", "Time entries"), entity="projects.timesheets", icon="Timer"),
    ],
    # Libellés complets (l'objet est nommé) : « Mes vues » reconnaît un chiffre clé quand la demande cite son libellé
    kpis=[
        Kpi("active_projects", ("Projets en cours", "Active projects"), _active_projects, icon="FolderKanban",
            foot=("{n} tâche(s) à terminer", "{n} task(s) to complete"), path="/projets/projets?f_status=active"),
        Kpi("hours_month", ("Heures saisies ce mois", "Hours logged this month"), _hours_month, icon="Timer",
            foot=("heures, {n} saisie(s) de temps", "hours, {n} time record(s)"), path="/projets/temps"),
        Kpi("time_to_invoice", ("Temps à facturer", "Time to invoice"), _time_to_invoice, unit="money", icon="ReceiptText",
            foot=("{n} projet(s) concerné(s), HT", "{n} project(s), excl. VAT"), path="/projets/projets"),
    ],
    shortcuts=[Shortcut("new_timesheet", ("Saisir du temps", "Log time"), "/projets/temps?new=1", icon="Timer")],
    seed_demo=seed_demo,
    reset_tables=("projects_timesheets", "projects_tasks", "projects_projects"),
)
