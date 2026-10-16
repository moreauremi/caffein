# SPDX-License-Identifier: AGPL-3.0-or-later
"""Données de démonstration : trois projets du studio pour ses clients (une refonte d'identité et un site vitrine en
cours, un kit de papeterie terminé), leurs tâches et le temps passé par l'équipe ces trois dernières semaines, pas encore
facturé. La démonstration ne crée aucune facture : « Facturer les temps » reste à essayer."""

from __future__ import annotations

from datetime import date, timedelta

from ... import db
from ...core import entities
from ...core import modules as registry
from ...core.modules import MANAGE
from ...utils import today

NOVA, LEMOINE, KAIROS = "Refonte de l'identité Atelier Nova", "Site vitrine Boulangerie Lemoine", "Kit papeterie Kairos"

# (nom, client, statut, chef de projet, début et fin (jours par rapport à aujourd'hui), budget en heures, taux horaire,
#  description, tâches [(intitulé, statut, priorité, échéance (jours), temps estimé, attribuée à)])
PROJECTS = [
    (NOVA, "Atelier Nova", "active", "Camille Roux", -21, 30, 40, 65,
     "Nouvelle identité visuelle de l'atelier : audit de la marque, pistes créatives, puis charte graphique complète.",
     [("Audit de marque", "done", "normal", -14, 6, "Camille Roux"),
      ("Pistes créatives", "in_progress", "high", 3, 16, "Camille Roux"),
      ("Charte graphique", "todo", "normal", 10, 14, "Nina Lefèvre")]),
    (LEMOINE, "Boulangerie Lemoine", "active", "Alex Durand", -16, 25, 30, 60,
     "Site vitrine de cinq pages : la boulangerie, ses produits, ses horaires et un formulaire de contact.",
     [("Arborescence et contenus", "done", "normal", -9, 4, "Alex Durand"),
      ("Maquettes des pages", "in_progress", "urgent", -2, 12, "Camille Roux"),
      ("Intégration et mise en ligne", "todo", "normal", 20, 10, "Nina Lefèvre")]),
    (KAIROS, "Kairos Conseil", "done", "Hugo Martin", -24, -10, 12, 65,
     "Kit de papeterie aux couleurs du cabinet : cartes de visite, papier à en-tête et enveloppes, imprimés à l'atelier.",
     [("Maquette du kit", "done", "normal", -17, 5, "Camille Roux"),
      ("Fabrication et livraison", "done", "high", -12, 4, "Hugo Martin")]),
]

# (projet, tâche (None : sans tâche), salarié, il y a … jours, heures, description, facturable)
TIMESHEETS = [
    (NOVA, "Audit de marque", "Camille Roux", 20, 3.5, "Entretiens avec l'équipe et analyse de l'existant", True),
    (NOVA, "Audit de marque", "Alex Durand", 18, 2, "Restitution de l'audit au client", True),
    (NOVA, "Pistes créatives", "Camille Roux", 13, 4, "Recherches graphiques et planches de tendances", True),
    (NOVA, "Pistes créatives", "Nina Lefèvre", 11, 3, "Déclinaison des deux pistes retenues", True),
    (NOVA, None, "Alex Durand", 6, 1, "Point d'avancement interne", False),
    (NOVA, "Pistes créatives", "Camille Roux", 0, 2.5, "Préparation de la présentation des pistes", True),
    (LEMOINE, "Arborescence et contenus", "Alex Durand", 15, 2, "Atelier de cadrage avec Claire Lemoine", True),
    (LEMOINE, "Maquettes des pages", "Camille Roux", 9, 5, "Maquette de la page d'accueil", True),
    (LEMOINE, "Maquettes des pages", "Nina Lefèvre", 3, 3.5, "Maquettes des pages Produits et Contact", True),
    (KAIROS, "Maquette du kit", "Camille Roux", 19, 3, "Mise en page des cartes de visite et du papier à en-tête", True),
    (KAIROS, "Fabrication et livraison", "Hugo Martin", 16, 2.5, "Impression, façonnage et contrôle du kit", True),
    (KAIROS, None, "Léa Bernard", 15, 0.5, "Préparation du bon de livraison", False),
]


def _day(offset: int) -> str:
    return (today() + timedelta(days=offset)).isoformat()


def _worked_day(days_ago: int, employee_id: int | None) -> str:
    """Le jour visé, ou le jour ouvré précédent où le salarié était présent : pas de temps saisi un dimanche, un jour
    férié ou pendant une absence validée (calendrier et absences des RH quand elles sont actives)."""
    hr = None
    if registry.is_enabled("hr"):
        from ..hr import services as hr
    day: date = today() - timedelta(days=days_ago)
    for _ in range(30):
        working = hr.is_working_day(day) if hr else day.weekday() < 5
        if working and not (hr and employee_id and hr.is_absent(employee_id, day)):
            break
        day -= timedelta(days=1)
    return day.isoformat()


def seed_demo() -> None:
    projects, tasks, timesheets = (entities.get(f"projects.{name}") for name in ("projects", "tasks", "timesheets"))
    clients, employees = {}, {}
    if registry.is_enabled("sales"):
        clients = {r["name"]: r["id"] for r in db.fetch_all("SELECT id, name FROM clients")}
    if registry.is_enabled("hr"):
        employees = {r["full_name"]: r["id"] for r in db.fetch_all("SELECT id, full_name FROM hr_employees")}

    project_ids, task_ids = {}, {}
    for name, client, status, manager, start, end, budget, rate, text, project_tasks in PROJECTS:
        project_ids[name] = entities.save_row(projects, {
            "name": name, "client_id": clients.get(client), "manager_id": employees.get(manager), "status": status,
            "start_date": _day(start), "end_date": _day(end), "budget_hours": budget, "budget_amount": budget * rate,
            "hourly_rate": rate, "description": text,
        }, MANAGE)
        for title, task_status, priority, due, estimate, assignee in project_tasks:
            task_id = entities.save_row(tasks, {
                "project_id": project_ids[name], "title": title, "priority": priority, "due_date": _day(due),
                "estimate_hours": estimate, "assignee_id": employees.get(assignee),
            }, MANAGE)
            if task_status == "in_progress":
                entities.run_action(tasks, task_id, "start", {}, {}, MANAGE)
            elif task_status == "done":
                entities.run_action(tasks, task_id, "finish", {}, {}, MANAGE)
            task_ids[(name, title)] = task_id

    for project, task, employee, days_ago, spent, text, billable in TIMESHEETS:
        employee_id = employees.get(employee)
        entities.save_row(timesheets, {
            "date": _worked_day(days_ago, employee_id), "project_id": project_ids[project],
            "task_id": task_ids.get((project, task)), "employee_id": employee_id, "hours": spent, "description": text,
            "billable": billable,
        }, MANAGE)
