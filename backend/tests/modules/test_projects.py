# SPDX-License-Identifier: AGPL-3.0-or-later
"""Projets : projets (numérotation, heures, avancement, temps à facturer), tâches (actions, retard), temps passés
(contrôles, montants, verrouillage), facturation des temps (facture brouillon des Ventes), droits, modules RH et Ventes
désactivés, chiffres clés, « Mes vues », vue en colonnes, export et données de démonstration."""

import csv
import io
from datetime import timedelta

import pytest

from caffein import dashboard, db
from caffein.core import entities
from caffein.core import modules as registry
from caffein.core.errors import Conflict
from caffein.core.modules import MANAGE
from caffein.modules.projects import figures
from caffein.modules.projects.entities import PROJECTS, TASKS
from caffein.utils import fmt_date, fmt_money, today

from .helpers import disable_module, login_as, make_member

BASE = "/api/data/projects"
FIGURES = ("hours_spent", "progress", "remaining_hours", "tasks_open", "to_invoice_hours", "to_invoice_amount")
INVOICED = "Temps déjà facturé : il ne se modifie plus."
NOT_NOW = "Cette action n'est pas possible dans l'état actuel de la fiche."
NOVA, LEMOINE, KAIROS = "Refonte de l'identité Atelier Nova", "Site vitrine Boulangerie Lemoine", "Kit papeterie Kairos"


@pytest.fixture()
def restore_modules():
    yield
    registry.enable_all()


def _day(offset: int = 0) -> str:
    return (today() + timedelta(days=offset)).isoformat()


def _client(name: str) -> int:
    return db.fetch_one("SELECT id FROM clients WHERE name = ?", (name,))["id"]


def _employee(name: str) -> int:
    return db.fetch_one("SELECT id FROM hr_employees WHERE full_name = ?", (name,))["id"]


def _error(res, status: int = 400) -> str:
    assert res.status_code == status, res.text
    return res.json()["detail"]


def _post(client, entity: str, data: dict) -> dict:
    res = client.post(f"{BASE}/{entity}", json=data)
    assert res.status_code == 201, res.text
    return res.json()


def _get(client, entity: str, row: dict) -> dict:
    res = client.get(f"{BASE}/{entity}/{row['id']}")
    assert res.status_code == 200, res.text
    return res.json()


def _project(client, name: str = "Catalogue Maison Verde", **extra) -> dict:
    return _post(client, "projects", {"name": name, **extra})


def _task(client, project: dict, title: str, **extra) -> dict:
    return _post(client, "tasks", {"project_id": project["id"], "title": title, **extra})


def _time(client, project: dict, hours, task: dict | None = None, **extra) -> dict:
    return _post(client, "timesheets", {"project_id": project["id"], "task_id": task["id"] if task else None,
                                        "hours": hours, **extra})


def _act(client, entity: str, row: dict, action: str):
    return client.post(f"{BASE}/{entity}/{row['id']}/actions/{action}", json={})


def _invoices() -> int:
    return db.fetch_one("SELECT COUNT(*) AS n FROM invoices")["n"]


def _invoice(client, invoice_id: int) -> dict:
    res = client.get(f"/api/invoices/{invoice_id}")
    assert res.status_code == 200, res.text
    return res.json()


# ═════════════════════════════════════════════════════════════════════════
# Projets : numérotation, valeurs par défaut, chiffres calculés
# ═════════════════════════════════════════════════════════════════════════
def test_project_numbering_defaults_and_figures(client):
    count = db.fetch_one("SELECT COUNT(*) AS n FROM projects_projects")["n"]
    project = _project(client, client_id=_client("Maison Verde"), budget_hours=20, code="PIRATE", hours_spent=99,
                       to_invoice_amount=1)
    assert project["code"] == f"PRJ-{today().year}-{count + 1:04d}"
    assert project["status"] == "planned" and project["hourly_rate"] == 65 and project["client_id__label"] == "Maison Verde"
    assert {k: project[k] for k in FIGURES} == {"hours_spent": 0, "progress": 0, "remaining_hours": 20, "tasks_open": 0,
                                                "to_invoice_hours": 0, "to_invoice_amount": 0}
    assert project["_actions"] == [] and project["_locked"] is None  # rien à facturer
    assert _project(client, "Second projet")["code"] == f"PRJ-{today().year}-{count + 2:04d}"

    layout, proof = _task(client, project, "Mise en page"), _task(client, project, "Relecture")
    _time(client, project, 2.25, layout)
    _time(client, project, "1,5", layout)
    _time(client, project, 3, proof)
    _time(client, project, 0.75)                      # sans tâche
    _time(client, project, 1, proof, billable=False)  # compté dans les heures passées, jamais facturé
    _act(client, "tasks", proof, "finish")
    record = _get(client, "projects", project)
    # 8,5 h passées sur 20 h ; 7,5 h facturables : 3,75 h × 65 + 3 h × 65 + 0,75 h × 65
    assert {k: record[k] for k in FIGURES} == {"hours_spent": 8.5, "progress": 42.5, "remaining_hours": 11.5,
                                               "tasks_open": 1, "to_invoice_hours": 7.5, "to_invoice_amount": 487.5}
    assert record["_actions"] == ["invoice_time"]
    # la liste calcule les mêmes chiffres, par des requêtes groupées
    listed = next(r for r in client.get(f"{BASE}/projects", params={"size": 200}).json()["rows"] if r["id"] == project["id"])
    assert {k: listed[k] for k in FIGURES} == {k: record[k] for k in FIGURES}
    # dépassement du budget : avancement au-delà de 100 %, heures restantes négatives
    over = client.put(f"{BASE}/projects/{project['id']}", json={"budget_hours": 8, "code": "X"}).json()
    assert (over["progress"], over["remaining_hours"], over["code"]) == (106.3, -0.5, project["code"])
    without = client.put(f"{BASE}/projects/{project['id']}", json={"budget_hours": None}).json()
    assert without["progress"] is None and without["remaining_hours"] is None

    # aperçu pendant la saisie : le serveur recalcule avec les valeurs saisies, sans rien enregistrer
    preview = client.post(f"{BASE}/projects/preview", params={"id": project["id"]},
                          json={"hourly_rate": 70, "budget_hours": 0}).json()["computed"]
    assert preview == {"hours_spent": 8.5, "progress": None, "remaining_hours": -8.5, "tasks_open": 1,
                       "to_invoice_hours": 7.5, "to_invoice_amount": 525}
    assert _get(client, "projects", project)["hourly_rate"] == 65
    empty = client.post(f"{BASE}/projects/preview", json={}).json()["computed"]
    assert empty == {"hours_spent": 0, "progress": None, "remaining_hours": None, "tasks_open": 0,
                     "to_invoice_hours": 0, "to_invoice_amount": 0}
    invalid = client.post(f"{BASE}/projects/preview", json={"budget_hours": "beaucoup", "hourly_rate": -3}).json()["computed"]
    assert invalid["progress"] is None and invalid["to_invoice_amount"] == 0


def test_project_validation(client):
    nova = _client("Atelier Nova")
    cases = (
        ({}, "Nom du projet : obligatoire."),
        ({"name": "  "}, "Nom du projet : obligatoire."),
        ({"name": "X" * 121}, "Nom du projet : 120 caractères au plus."),
        ({"name": "X", "start_date": _day(), "end_date": _day(-1)}, "Date de fin : elle ne peut pas précéder la date de début."),
        ({"name": "X", "end_date": "31/02/2026"}, "Date de fin : date invalide."),
        ({"name": "X", "budget_hours": -1}, "Budget en heures : 0 au minimum."),
        ({"name": "X", "budget_amount": "beaucoup"}, "Budget HT : nombre attendu."),
        ({"name": "X", "hourly_rate": -5}, "Taux horaire facturé : 0 au minimum."),
        ({"name": "X", "status": "archived"}, "Statut : valeur non proposée."),
        ({"name": "X", "status": ""}, "Statut : obligatoire."),
        ({"name": "X", "client_id": 999999}, "Client : fiche introuvable."),
        ({"name": "X", "client_id": 10**20}, "Client : nombre hors limites."),
        ({"name": "X", "manager_id": 999999}, "Chef de projet : fiche introuvable."),
    )
    for data, message in cases:
        assert _error(client.post(f"{BASE}/projects", json=data)) == message, data
    # un projet peut commencer et finir le même jour ; son statut se choisit dans la fiche
    project = _project(client, "Atelier photo", client_id=nova, start_date=_day(), end_date=_day(), budget_amount="1 250,5")
    assert project["budget_amount"] == 1250.5
    url = f"{BASE}/projects/{project['id']}"
    assert client.put(url, json={"status": "active"}).json()["status"] == "active"
    assert _error(client.put(url, json={"end_date": _day(-2)})) == "Date de fin : elle ne peut pas précéder la date de début."
    assert _error(client.put(url, json={"status": None})) == "Statut : obligatoire."
    found = client.get(f"{BASE}/projects", params={"q": project["code"]}).json()
    assert [r["id"] for r in found["rows"]] == [project["id"]]
    mine = client.get(f"{BASE}/projects", params={"f_client_id": nova, "size": 200}).json()["rows"]
    assert project["id"] in [r["id"] for r in mine] and {r["client_id"] for r in mine} == {nova}
    # choix d'un projet dans un formulaire : nom et numéro
    options = client.get(f"{BASE}/projects/options", params={"q": "atelier photo"}).json()
    assert options == [{"id": project["id"], "label": "Atelier photo", "sublabel": project["code"]}]


# ═════════════════════════════════════════════════════════════════════════
# Tâches : actions, retard, contrôles
# ═════════════════════════════════════════════════════════════════════════
def test_task_actions_and_overdue_flag(client):
    project = _project(client)
    late = _task(client, project, "Bon à tirer", due_date=_day(-1), estimate_hours=3)
    assert (late["status"], late["priority"], late["overdue"], late["spent_hours"]) == ("todo", "normal", True, 0)
    assert set(late["_actions"]) == {"start", "finish"}

    started = _act(client, "tasks", late, "start").json()
    assert started["message"] == "Tâche « Bon à tirer » démarrée."
    assert started["row"]["status"] == "in_progress" and started["row"]["overdue"] is True
    assert started["row"]["_actions"] == ["finish"]
    assert _error(_act(client, "tasks", late, "start"), 409) == NOT_NOW
    finished = _act(client, "tasks", late, "finish").json()
    assert finished["message"] == "Tâche « Bon à tirer » terminée."
    assert finished["row"]["status"] == "done" and finished["row"]["overdue"] is False and finished["row"]["_actions"] == []
    assert _error(_act(client, "tasks", late, "finish"), 409) == NOT_NOW
    assert _error(_act(client, "tasks", late, "start"), 409) == NOT_NOW
    # le statut se change aussi dans la fiche : une tâche rouverte et échue est de nouveau en retard
    reopened = client.put(f"{BASE}/tasks/{late['id']}", json={"status": "todo"}).json()
    assert reopened["overdue"] is True and set(reopened["_actions"]) == {"start", "finish"}

    # une tâche à faire se termine directement
    quick = _task(client, project, "Envoi des fichiers", priority="urgent")
    assert _act(client, "tasks", quick, "finish").json()["row"]["status"] == "done"
    # échéance aujourd'hui, demain, ou sans échéance : pas en retard
    today_task = _task(client, project, "Échéance du jour", due_date=_day())
    tomorrow = _task(client, project, "Échéance demain", due_date=_day(1))
    undated = _task(client, project, "Sans échéance")
    assert [t["overdue"] for t in (today_task, tomorrow, undated)] == [False, False, False]
    rows = {r["id"]: r for r in client.get(f"{BASE}/tasks", params={"f_project_id": project["id"]}).json()["rows"]}
    assert {i: r["overdue"] for i, r in rows.items()} == {late["id"]: True, quick["id"]: False, today_task["id"]: False,
                                                         tomorrow["id"]: False, undated["id"]: False}
    # liste triée par échéance, les tâches sans échéance à la fin
    assert list(rows) == [late["id"], today_task["id"], tomorrow["id"], undated["id"], quick["id"]]
    assert [r["id"] for r in client.get(f"{BASE}/tasks", params={"f_project_id": project["id"], "f_status": "done"})
            .json()["rows"]] == [quick["id"]]
    # aperçu d'une tâche en cours de saisie
    preview = client.post(f"{BASE}/tasks/preview", json={"status": "in_progress", "due_date": _day(-3)}).json()
    assert preview["computed"] == {"spent_hours": 0, "overdue": True}
    assert client.post(f"{BASE}/tasks/preview", json={}).json()["computed"] == {"spent_hours": 0, "overdue": False}

    # deux actions simultanées sur la même tâche ne passent pas toutes les deux
    stale = _get(client, "tasks", undated)
    client.put(f"{BASE}/tasks/{undated['id']}", json={"status": "done"})
    start = next(a for a in TASKS.actions if a.key == "start")
    with pytest.raises(Conflict, match="La tâche vient d'être modifiée par ailleurs : rechargez-la."):
        start.run(stale, {}, {})


def test_task_validation(client):
    project, other = _project(client), _project(client, "Autre projet")
    cases = (
        ({"title": "Sans projet"}, "Projet : obligatoire."),
        ({"project_id": project["id"]}, "Intitulé : obligatoire."),
        ({"project_id": 999999, "title": "X"}, "Projet : fiche introuvable."),
        ({"project_id": project["id"], "title": "X", "priority": "critique"}, "Priorité : valeur non proposée."),
        ({"project_id": project["id"], "title": "X", "status": "blocked"}, "Statut : valeur non proposée."),
        ({"project_id": project["id"], "title": "X", "estimate_hours": -1}, "Temps estimé (heures) : 0 au minimum."),
        ({"project_id": project["id"], "title": "X", "assignee_id": 999999}, "Attribuée à : fiche introuvable."),
        ({"project_id": project["id"], "title": "X", "due_date": "demain"}, "Échéance : date invalide."),
    )
    for data, message in cases:
        assert _error(client.post(f"{BASE}/tasks", json=data)) == message, data
    task = _task(client, project, "Recherches", assignee_id=_employee("Camille Roux"))
    assert task["assignee_id__label"] == "Camille Roux" and task["project_id__label"] == "Catalogue Maison Verde"
    # sans temps saisi, une tâche change de projet ; ensuite, plus
    moved = client.put(f"{BASE}/tasks/{task['id']}", json={"project_id": other["id"]}).json()
    assert moved["project_id"] == other["id"]
    _time(client, other, 2, task)
    assert _get(client, "tasks", task)["spent_hours"] == 2
    res = client.put(f"{BASE}/tasks/{task['id']}", json={"project_id": project["id"]})
    assert _error(res) == "Projet : du temps est déjà saisi sur cette tâche ; elle ne peut plus changer de projet."
    assert client.put(f"{BASE}/tasks/{task['id']}", json={"title": "Recherches graphiques"}).status_code == 200
    # un projet annulé ne reçoit plus de tâche
    client.put(f"{BASE}/projects/{project['id']}", json={"status": "cancelled"})
    res = client.post(f"{BASE}/tasks", json={"project_id": project["id"], "title": "Trop tard"})
    assert _error(res) == "Projet : ce projet est annulé, on n'y ajoute plus de tâche."


# ═════════════════════════════════════════════════════════════════════════
# Temps passés : contrôles, montants
# ═════════════════════════════════════════════════════════════════════════
def test_timesheet_validation(client):
    project, other = _project(client), _project(client, "Autre projet")
    task, foreign = _task(client, project, "Maquette"), _task(client, other, "Tâche d'un autre projet")

    def post(data):
        return client.post(f"{BASE}/timesheets", json={"project_id": project["id"], "hours": 1, **data})

    cases = (
        ({"project_id": None}, "Projet : obligatoire."),
        ({"project_id": 999999}, "Projet : fiche introuvable."),
        ({"hours": None}, "Heures : obligatoire."),
        ({"hours": "beaucoup"}, "Heures : nombre attendu."),
        ({"hours": 0}, "Heures : elles doivent être supérieures à zéro."),
        ({"hours": -2}, "Heures : elles doivent être supérieures à zéro."),
        ({"hours": 0.004}, "Heures : elles doivent être supérieures à zéro."),  # moins d'un centième d'heure
        ({"hours": 24.5}, "Heures : 24 au maximum."),
        ({"task_id": foreign["id"]}, "Tâche : elle n'appartient pas à ce projet."),
        ({"task_id": 999999}, "Tâche : fiche introuvable."),
        ({"employee_id": 999999}, "Salarié : fiche introuvable."),
        ({"date": ""}, "Date : obligatoire."),
        ({"date": "2026-02-30"}, "Date : date invalide."),
        ({"billable": "peut-être"}, "Facturable : oui ou non attendu."),
        ({"description": "x" * 301}, "Description : 300 caractères au plus."),
    )
    for data, message in cases:
        assert _error(post(data)) == message, data
    entry = _time(client, project, 24, task)  # une journée entière, sans salarié
    assert entry["date"] == _day() and entry["billable"] is True and entry["invoiced"] is False
    assert entry["task_id__label"] == "Maquette" and entry["project_id__label"] == "Catalogue Maison Verde"
    # changer de projet sans changer de tâche : refusé
    res = client.put(f"{BASE}/timesheets/{entry['id']}", json={"project_id": other["id"]})
    assert _error(res) == "Tâche : elle n'appartient pas à ce projet."
    moved = client.put(f"{BASE}/timesheets/{entry['id']}", json={"project_id": other["id"], "task_id": foreign["id"]})
    assert moved.status_code == 200 and moved.json()["project_id"] == other["id"]

    # projet annulé : plus de nouveau temps, mais un temps déjà saisi se corrige
    kept = _time(client, project, 2)
    client.put(f"{BASE}/projects/{project['id']}", json={"status": "cancelled"})
    assert _error(post({})) == "Projet : ce projet est annulé, on n'y saisit plus de temps."
    assert client.put(f"{BASE}/timesheets/{kept['id']}", json={"description": "Corrigé"}).status_code == 200
    res = client.put(f"{BASE}/timesheets/{moved.json()['id']}", json={"project_id": project["id"], "task_id": None})
    assert _error(res) == "Projet : ce projet est annulé, on n'y saisit plus de temps."


def test_a_day_holds_at_most_24_hours_per_employee(client):
    employee = client.post("/api/data/hr/employees", json={"first_name": "Jeanne", "last_name": "Morel"}).json()["id"]
    project = _project(client)
    day = _day(-1)
    long = _time(client, project, 20, employee_id=employee, date=day)
    res = client.post(f"{BASE}/timesheets", json={"project_id": project["id"], "hours": 5, "employee_id": employee, "date": day})
    assert _error(res) == "Heures : le salarié a déjà 20 h saisies ce jour-là ; une journée ne peut pas dépasser 24 h."
    short = _time(client, project, 4, employee_id=employee, date=day)          # 24 h : la journée est pleine
    _time(client, project, 6, employee_id=employee, date=_day(-2))             # un autre jour
    _time(client, project, 6, date=day)                                        # sans salarié
    _time(client, project, 6, employee_id=_employee("Hugo Martin"), date=day)  # un autre salarié
    # une modification ne compte pas le temps qu'elle remplace
    res = client.put(f"{BASE}/timesheets/{short['id']}", json={"hours": 4.5})
    assert _error(res) == "Heures : le salarié a déjà 20 h saisies ce jour-là ; une journée ne peut pas dépasser 24 h."
    assert client.put(f"{BASE}/timesheets/{long['id']}", json={"hours": 19.5}).status_code == 200
    assert client.put(f"{BASE}/timesheets/{short['id']}", json={"hours": 4.5}).status_code == 200


def test_timesheet_amounts(client):
    project = _project(client, hourly_rate=65)
    entry = _time(client, project, 1.5)
    assert entry["amount"] == 97.5
    free = _time(client, project, 2, billable=False)
    assert free["amount"] == 0
    # heures au centième, la moitié vers le haut : 1,005 h → 1,01 h → 65,65 €
    rounded = _time(client, project, "1,005")
    assert rounded["hours"] == 1.01 and rounded["amount"] == 65.65
    # le montant d'un temps pas encore facturé suit le taux du projet
    client.put(f"{BASE}/projects/{project['id']}", json={"hourly_rate": 80})
    assert _get(client, "timesheets", entry)["amount"] == 120
    rows = {r["id"]: r for r in client.get(f"{BASE}/timesheets", params={"f_project_id": project["id"]}).json()["rows"]}
    assert {i: r["amount"] for i, r in rows.items()} == {entry["id"]: 120, free["id"]: 0, rounded["id"]: 80.8}
    billable = client.get(f"{BASE}/timesheets", params={"f_project_id": project["id"], "f_billable": "0"}).json()["rows"]
    assert [r["id"] for r in billable] == [free["id"]]
    # aperçu : saisie neuve facturable par défaut, valeurs manquantes ou invalides comptées pour zéro
    def preview(data):
        return client.post(f"{BASE}/timesheets/preview", json=data).json()["computed"]

    assert preview({}) == {"amount": 0, "invoiced": False, "invoice_number": ""}
    assert preview({"project_id": project["id"], "hours": 2})["amount"] == 160
    assert preview({"project_id": project["id"], "hours": 2, "billable": False})["amount"] == 0
    assert preview({"project_id": project["id"], "hours": "deux"})["amount"] == 0
    assert preview({"project_id": project["id"], "hours": -1})["amount"] == 0
    # une case « facturable » laissée vide garde sa valeur
    assert client.put(f"{BASE}/timesheets/{free['id']}", json={"billable": None}).json()["billable"] is False


# ═════════════════════════════════════════════════════════════════════════
# Facturation des temps
# ═════════════════════════════════════════════════════════════════════════
def test_invoice_time_creates_one_draft_invoice(client):
    nova = _client("Atelier Nova")
    project = _project(client, "Affiches Atelier Nova", client_id=nova, status="active")
    logo, variants = _task(client, project, "Logo animé"), _task(client, project, "Déclinaisons")
    billed = [
        _time(client, project, 2, logo, date=_day(-5)),
        _time(client, project, 3.5, variants, date=_day(-3)),
        _time(client, project, 1.25, logo, date=_day(-2)),
        _time(client, project, 0.5, date=_day(-1)),  # sans tâche : « Temps passé »
    ]
    free = _time(client, project, 2, variants, billable=False, date=_day(-1))
    other = _project(client, "Autre projet Nova", client_id=nova)
    elsewhere = _time(client, other, 4)
    before = _invoices()
    assert _get(client, "projects", project)["to_invoice_amount"] == 471.25

    res = _act(client, "projects", project, "invoice_time")
    assert res.status_code == 200, res.text
    assert res.json()["message"] == (f"Facture brouillon créée : 7,25 h pour {fmt_money(471.25)} HT. "
                                     "Vérifiez-la puis émettez-la dans Ventes, Factures et devis.")
    assert _invoices() == before + 1
    entry = _get(client, "timesheets", billed[0])
    invoice = _invoice(client, entry["invoice_id"])
    assert (invoice["kind"], invoice["status"], invoice["number"]) == ("invoice", "draft", None)
    assert invoice["client_id"] == nova and invoice["title"] == "Projet Affiches Atelier Nova"
    # une ligne par tâche, dans l'ordre du premier temps saisi, puis les temps sans tâche ; quantité = heures
    assert [(i["description"], i["quantity"], i["unit_price"]) for i in invoice["items"]] == [
        ("Tâche : Logo animé", 3.25, 65), ("Tâche : Déclinaisons", 3.5, 65), ("Temps passé", 0.5, 65)]
    assert (invoice["subtotal"], invoice["vat_amount"], invoice["total"]) == (471.25, 94.25, 565.5)
    assert invoice["delivery_date"] == _day(-1)
    assert invoice["notes"] == f"Temps passés du {fmt_date(_day(-5))} au {fmt_date(_day(-1))} (projet {project['code']})."

    # les temps repris sont facturés et verrouillés ; le temps non facturable et l'autre projet ne bougent pas
    for row in billed:
        record = _get(client, "timesheets", row)
        assert record["invoiced"] is True and record["invoice_id"] == invoice["id"] and record["invoice_number"] == "brouillon"
        assert record["_locked"] == INVOICED and record["_deletable"] is False
    assert _error(client.put(f"{BASE}/timesheets/{billed[0]['id']}", json={"hours": 9}), 409) == INVOICED
    res = client.delete(f"{BASE}/timesheets/{billed[1]['id']}")
    assert _error(res, 409) == "Temps déjà facturé : il ne peut pas être supprimé."
    for row in (free, elsewhere):
        record = _get(client, "timesheets", row)
        assert record["invoiced"] is False and record["invoice_id"] is None and record["_locked"] is None
    listed = {r["id"]: r for r in client.get(f"{BASE}/timesheets", params={"f_project_id": project["id"]}).json()["rows"]}
    assert {i: r["invoiced"] for i, r in listed.items()} == {**{r["id"]: True for r in billed}, free["id"]: False}

    # plus rien à facturer : l'action disparaît et ne passe plus ; les heures passées ne changent pas
    record = _get(client, "projects", project)
    assert (record["to_invoice_hours"], record["to_invoice_amount"], record["hours_spent"]) == (0, 0, 9.25)
    assert record["_actions"] == []
    assert _error(_act(client, "projects", project, "invoice_time"), 409) == NOT_NOW
    assert _invoices() == before + 1
    assert _get(client, "projects", other)["to_invoice_hours"] == 4

    # un nouveau temps, et le temps devenu facturable, partent dans la facture suivante, seuls
    _time(client, project, 1, logo)
    client.put(f"{BASE}/timesheets/{free['id']}", json={"billable": True})
    assert _get(client, "projects", project)["to_invoice_hours"] == 3
    second = _act(client, "projects", project, "invoice_time").json()
    assert second["message"] == (f"Facture brouillon créée : 3 h pour {fmt_money(195)} HT. "
                                 "Vérifiez-la puis émettez-la dans Ventes, Factures et devis.")
    second_invoice = _invoice(client, _get(client, "timesheets", free)["invoice_id"])
    assert second_invoice["id"] != invoice["id"]
    assert [(i["description"], i["quantity"]) for i in second_invoice["items"]] == [("Tâche : Déclinaisons", 2),
                                                                                   ("Tâche : Logo animé", 1)]
    assert second_invoice["notes"] == f"Temps passés du {fmt_date(_day(-1))} au {fmt_date(_day())} (projet {project['code']})."
    assert len(_invoice(client, invoice["id"])["items"]) == 3  # la première facture n'a pas changé


def test_invoice_lines_are_rounded_like_the_invoice(client):
    """Le montant à facturer est celui de la facture : arrondi au centime ligne par ligne (2 × 5,005 → 2 × 5,01)."""
    project = _project(client, client_id=_client("Pixel & Co"), hourly_rate=10.01)
    _time(client, project, 0.5, _task(client, project, "Première tâche"))
    _time(client, project, 0.5, _task(client, project, "Seconde tâche"))
    record = _get(client, "projects", project)
    assert record["to_invoice_hours"] == 1 and record["to_invoice_amount"] == 10.02
    _act(client, "projects", project, "invoice_time")
    invoice_id = db.fetch_one("SELECT invoice_id FROM projects_timesheets WHERE project_id = ? LIMIT 1", (project["id"],))
    invoice = _invoice(client, invoice_id["invoice_id"])
    assert invoice["subtotal"] == 10.02 and invoice["delivery_date"] == _day()
    assert invoice["notes"] == f"Temps passé le {fmt_date(_day())} (projet {project['code']})."  # un seul jour
    assert figures.amount([{"hours": 0.5}, {"hours": 0.5}], 10.01) == 10.02
    assert figures.amount([{"hours": 3}], None) == 0 and figures.amount([], 65) == 0


def test_invoice_time_refusals(client, restore_modules):
    before = _invoices()
    # sans client
    orphan = _project(client, "Projet sans client")
    entry = _time(client, orphan, 2)
    res = _act(client, "projects", orphan, "invoice_time")
    assert _error(res) == "Client : choisissez le client du projet avant de facturer les temps."
    # sans taux horaire
    free_rate = _project(client, "Projet offert", client_id=_client("Maison Verde"), hourly_rate=0)
    _time(client, free_rate, 3)
    assert _get(client, "projects", free_rate)["to_invoice_hours"] == 3
    res = _act(client, "projects", free_rate, "invoice_time")
    assert _error(res) == "Taux horaire facturé : renseignez un taux supérieur à zéro avant de facturer les temps."
    assert _invoices() == before and _get(client, "timesheets", entry)["invoiced"] is False

    # un chef de projet sans droit d'écriture sur les Ventes ne crée pas de facture
    project = _project(client, "Projet de l'atelier", client_id=_client("Kairos Conseil"))
    _time(client, project, 1.5)
    manager = make_member("chef-projet@test.local", "production", {"projects": "write"})
    member = login_as("chef-projet@test.local")
    res = member.post(f"{BASE}/projects/{project['id']}/actions/invoice_time", json={})
    assert _error(res, 403) == "Ventes : il faut le droit d'écriture sur ce module pour créer la facture."
    assert _invoices() == before
    client.put(f"/api/users/{manager['id']}/permissions", json={"overrides": {"projects": "write", "sales": "write"}})
    assert member.post(f"{BASE}/projects/{project['id']}/actions/invoice_time", json={}).status_code == 200
    assert _invoices() == before + 1

    # sans les Ventes : le client disparaît, la facturation explique comment faire
    _time(client, project, 1)
    disable_module(client, "sales")
    record = _get(client, "projects", project)
    assert "client_id" not in record and record["to_invoice_hours"] == 1 and record["_actions"] == ["invoice_time"]
    res = _act(client, "projects", project, "invoice_time")
    assert _error(res) == ("Ventes : le module est désactivé ; un administrateur peut l'activer dans Paramètres → Modules "
                           "pour facturer les temps.")
    assert _invoices() == before + 1


def test_deleted_or_cancelled_invoice_releases_the_time(client):
    project = _project(client, "Brochure Kairos", client_id=_client("Kairos Conseil"))
    task = _task(client, project, "Mise en page")
    entries = [_time(client, project, 3, task, date=_day(-2)), _time(client, project, 1.5, task)]
    _act(client, "projects", project, "invoice_time")
    first = _get(client, "timesheets", entries[0])["invoice_id"]
    # la facture brouillon est supprimée dans les Ventes : les temps redeviennent à facturer et modifiables
    assert client.delete(f"/api/invoices/{first}").status_code == 204
    record = _get(client, "timesheets", entries[0])
    assert record["invoiced"] is False and record["_locked"] is None and record["invoice_number"] == ""
    project_row = _get(client, "projects", project)
    assert project_row["to_invoice_hours"] == 4.5 and project_row["_actions"] == ["invoice_time"]
    assert client.put(f"{BASE}/timesheets/{entries[1]['id']}", json={"hours": 2}).status_code == 200

    _act(client, "projects", project, "invoice_time")
    second = _get(client, "timesheets", entries[0])["invoice_id"]
    assert second != first and _invoice(client, second)["subtotal"] == 325  # 5 h × 65
    # émise : le numéro de la facture apparaît sur les temps
    issued = client.post(f"/api/invoices/{second}/finalize")
    assert issued.status_code == 200, issued.text
    assert _get(client, "timesheets", entries[1])["invoice_number"] == issued.json()["number"]
    # le taux facturé reste celui de la facture, même si le taux du projet change ensuite
    client.put(f"{BASE}/projects/{project['id']}", json={"hourly_rate": 80})
    assert _get(client, "timesheets", entries[0])["amount"] == 195
    assert _get(client, "projects", project)["to_invoice_amount"] == 0
    # facture annulée : les temps sont de nouveau à facturer, au taux actuel du projet
    assert client.post(f"/api/invoices/{second}/cancel").status_code == 200
    record = _get(client, "timesheets", entries[0])
    assert record["invoiced"] is False and record["amount"] == 240 and record["_locked"] is None
    assert _get(client, "projects", project)["to_invoice_amount"] == 400


def test_time_is_never_invoiced_twice(client, monkeypatch):
    project = _project(client, "Double clic", client_id=_client("Pixel & Co"))
    entry = _time(client, project, 2)
    stale = entities.get_row(PROJECTS, project["id"], MANAGE)
    invoice_time = next(a for a in PROJECTS.actions if a.key == "invoice_time")
    entries = figures.unbilled_entries([project["id"]])
    before = _invoices()
    assert entities.run_action(PROJECTS, project["id"], "invoice_time", {}, {}, MANAGE).startswith("Facture brouillon")
    # la fiche affichée avant la facturation : plus rien à facturer
    with pytest.raises(Conflict, match="Il n'y a plus de temps à facturer sur ce projet : rechargez-le."):
        invoice_time.run(stale, {}, {"module_level": MANAGE})
    # deux facturations au même instant : la seconde ne rattache rien, et sa facture brouillon disparaît
    monkeypatch.setattr(figures, "unbilled_entries", lambda project_ids=None: entries)
    with pytest.raises(Conflict, match="viennent d'être modifiés ou facturés par ailleurs"):
        invoice_time.run(stale, {}, {"module_level": MANAGE})
    assert _invoices() == before + 1
    assert _get(client, "timesheets", entry)["invoice_id"] == db.fetch_one("SELECT MAX(id) AS id FROM invoices")["id"]


# ═════════════════════════════════════════════════════════════════════════
# Suppression des fiches utilisées
# ═════════════════════════════════════════════════════════════════════════
def test_used_records_cannot_be_deleted(client):
    project = _project(client)
    task = _task(client, project, "Maquette")
    res = client.delete(f"{BASE}/projects/{project['id']}")
    assert _error(res, 409) == "Suppression impossible : cette fiche est utilisée ailleurs (tâches : 1)."
    employee = client.post("/api/data/hr/employees", json={"first_name": "Jeanne", "last_name": "Morel"}).json()
    entry = _time(client, project, 1, task, employee_id=employee["id"])
    res = client.delete(f"{BASE}/projects/{project['id']}")
    assert _error(res, 409) == "Suppression impossible : cette fiche est utilisée ailleurs (tâches : 1, temps passés : 1)."
    res = client.delete(f"{BASE}/tasks/{task['id']}")
    assert _error(res, 409) == "Suppression impossible : cette fiche est utilisée ailleurs (temps passés : 1)."
    # les fiches des autres modules désignées par un projet ne se suppriment pas non plus
    res = client.delete(f"/api/data/hr/employees/{employee['id']}")
    assert _error(res, 409) == "Suppression impossible : cette fiche est utilisée ailleurs (temps passés : 1)."
    lumen = client.post("/api/data/sales/clients", json={"name": "Studio Lumen"}).json()
    client.put(f"{BASE}/projects/{project['id']}", json={"client_id": lumen["id"]})
    res = client.delete(f"/api/data/sales/clients/{lumen['id']}")
    assert _error(res, 409) == "Suppression impossible : cette fiche est utilisée ailleurs (projets : 1)."
    # dans l'ordre : le temps (pas facturé), la tâche, puis le projet
    assert client.delete(f"{BASE}/timesheets/{entry['id']}").status_code == 204
    assert client.delete(f"/api/data/hr/employees/{employee['id']}").status_code == 204
    assert client.delete(f"{BASE}/tasks/{task['id']}").status_code == 204
    assert client.delete(f"{BASE}/projects/{project['id']}").status_code == 204
    assert client.get(f"{BASE}/projects/{project['id']}").status_code == 404


# ═════════════════════════════════════════════════════════════════════════
# Droits, modules désactivés, description
# ═════════════════════════════════════════════════════════════════════════
def test_readonly_role_cannot_write(client):
    project = _project(client, client_id=_client("Atelier Nova"))
    task = _task(client, project, "Maquette")
    entry = _time(client, project, 2, task)
    make_member("lecture-projets@test.local", "readonly")
    reader = login_as("lecture-projets@test.local")
    for name, row in (("projects", project), ("tasks", task), ("timesheets", entry)):
        assert reader.get(f"{BASE}/{name}").status_code == 200
        assert reader.get(f"{BASE}/{name}/export").status_code == 200
        record = reader.get(f"{BASE}/{name}/{row['id']}").json()
        assert record["_actions"] == [] and record["_deletable"] is False, name
        assert reader.post(f"{BASE}/{name}", json={}).status_code == 403, name
        assert reader.put(f"{BASE}/{name}/{row['id']}", json={}).status_code == 403, name
        assert reader.post(f"{BASE}/{name}/preview", json={}).status_code == 403, name
        assert reader.delete(f"{BASE}/{name}/{row['id']}").status_code == 403, name
        meta = reader.get("/api/meta").json()["entities"][f"projects.{name}"]
        assert not meta["can_create"] and not meta["can_edit"] and not meta["can_delete"], name
    for name, row, action in (("projects", project, "invoice_time"), ("tasks", task, "start"), ("tasks", task, "finish")):
        assert reader.post(f"{BASE}/{name}/{row['id']}/actions/{action}", json={}).status_code == 403, action
    home = reader.get("/api/home").json()
    assert {"projects.active_projects", "projects.hours_month", "projects.time_to_invoice"} <= {k["key"] for k in home["kpis"]}
    assert "projects.new_timesheet" not in {s["key"] for s in home["shortcuts"]}  # raccourci : niveau écriture
    assert _get(client, "tasks", task)["status"] == "todo" and _get(client, "timesheets", entry)["invoiced"] is False


def test_team_member_writes_but_does_not_delete(client):
    make_member("graphiste@test.local", "team")
    member = login_as("graphiste@test.local")
    meta = member.get("/api/meta").json()["entities"]["projects.timesheets"]
    assert meta["can_create"] and meta["can_edit"] and not meta["can_delete"]
    project = member.post(f"{BASE}/projects", json={"name": "Affiche du salon", "client_id": _client("Pixel & Co")}).json()
    task = member.post(f"{BASE}/tasks", json={"project_id": project["id"], "title": "Affiche"}).json()
    entry = member.post(f"{BASE}/timesheets", json={"project_id": project["id"], "task_id": task["id"], "hours": 3})
    assert entry.status_code == 201
    assert member.post(f"{BASE}/tasks/{task['id']}/actions/start", json={}).status_code == 200
    assert member.post(f"{BASE}/tasks/{task['id']}/actions/finish", json={}).status_code == 200
    assert member.post(f"{BASE}/projects/{project['id']}/actions/invoice_time", json={}).status_code == 200  # Ventes : écriture
    # suppression : niveau gestion
    spare = member.post(f"{BASE}/timesheets", json={"project_id": project["id"], "hours": 1}).json()
    assert member.delete(f"{BASE}/timesheets/{spare['id']}").status_code == 403
    assert member.delete(f"{BASE}/tasks/{task['id']}").status_code == 403
    assert member.delete(f"{BASE}/projects/{project['id']}").status_code == 403
    assert client.delete(f"{BASE}/timesheets/{spare['id']}").status_code == 204
    home = member.get("/api/home").json()
    assert "projects.new_timesheet" in {s["key"] for s in home["shortcuts"]}
    # un commercial n'a pas accès aux projets
    make_member("commercial-projets@test.local", "sales")
    seller = login_as("commercial-projets@test.local")
    assert seller.get(f"{BASE}/projects").status_code == 403
    assert seller.post(f"{BASE}/timesheets", json={"project_id": project["id"], "hours": 1}).status_code == 403
    assert not [k for k in seller.get("/api/home").json()["kpis"] if k["module"] == "projects"]


def test_projects_work_without_hr_and_sales(client, restore_modules):
    hugo = _employee("Hugo Martin")
    project = _project(client, "Signalétique de l'atelier", client_id=_client("Atelier Nova"), manager_id=hugo)
    task = _task(client, project, "Plans", assignee_id=hugo)
    entry = _time(client, project, 2, task, employee_id=hugo)
    invoiced = _project(client, "Projet facturé", client_id=_client("Atelier Nova"))
    billed = _time(client, invoiced, 1)
    _act(client, "projects", invoiced, "invoice_time")

    disable_module(client, "hr")
    meta = client.get("/api/meta").json()["entities"]
    names = {key: [f["name"] for f in meta[f"projects.{key}"]["fields"]] for key in ("projects", "tasks", "timesheets")}
    assert "manager_id" not in names["projects"] and "assignee_id" not in names["tasks"]
    assert "employee_id" not in names["timesheets"] and "client_id" in names["projects"]
    # la saisie continue sans les RH ; le salarié déjà choisi est conservé
    updated = client.put(f"{BASE}/timesheets/{entry['id']}", json={"hours": 2.5, "employee_id": 999999})
    assert updated.status_code == 200 and "employee_id" not in updated.json() and updated.json()["hours"] == 2.5
    assert db.fetch_one("SELECT employee_id FROM projects_timesheets WHERE id = ?", (entry["id"],))["employee_id"] == hugo
    assert _time(client, project, 1, task)["amount"] == 65
    assert client.get(f"{BASE}/timesheets", params={"f_employee_id": hugo}).status_code == 200
    assert client.post(f"{BASE}/timesheets/preview", json={"project_id": project["id"], "hours": 1}).status_code == 200

    disable_module(client, "sales")
    record = _get(client, "projects", project)
    assert "client_id" not in record and record["hours_spent"] == 3.5 and record["to_invoice_amount"] == 227.5
    # sans les Ventes, la facture ne se vérifie pas : un temps facturé le reste
    billed_row = _get(client, "timesheets", billed)
    assert billed_row["invoiced"] is True and billed_row["_locked"] == INVOICED and billed_row["invoice_number"] == ""
    assert _get(client, "projects", invoiced)["to_invoice_hours"] == 0
    assert client.get(f"{BASE}/projects/board").status_code == 200
    kpis = {k["key"]: k for k in client.get("/api/home").json()["kpis"]}
    assert kpis["projects.time_to_invoice"]["value"] >= 227.5


def test_disabled_projects_disappear(client, restore_modules):
    project = _project(client, client_id=_client("Maison Verde"))
    employee = client.post("/api/data/hr/employees", json={"first_name": "Jeanne", "last_name": "Morel"}).json()
    entry = _time(client, project, 2, employee_id=employee["id"])
    disable_module(client, "projects")
    for name in ("projects", "tasks", "timesheets"):
        assert client.get(f"{BASE}/{name}").status_code == 404
    assert client.get(f"{BASE}/timesheets/{entry['id']}").status_code == 404
    assert client.post(f"{BASE}/timesheets", json={"project_id": project["id"], "hours": 1}).status_code == 404
    assert client.post(f"{BASE}/projects/{project['id']}/actions/invoice_time", json={}).status_code == 404
    meta = client.get("/api/meta").json()
    assert "projects" not in [m["key"] for m in meta["modules"]]
    assert not [k for k in meta["entities"] if k.startswith("projects.")]
    home = client.get("/api/home").json()
    assert not [k for k in home["kpis"] if k["module"] == "projects"]
    assert not [s for s in home["shortcuts"] if s["module"] == "projects"]
    # ses données restent, et protègent toujours les fiches qu'elles désignent
    res = client.delete(f"/api/data/hr/employees/{employee['id']}")
    assert _error(res, 409) == "Suppression impossible : cette fiche est utilisée ailleurs (temps passés : 1)."
    assert client.put("/api/settings/modules/projects", json={"enabled": True}).status_code == 200
    assert _get(client, "timesheets", entry)["hours"] == 2


def test_meta_describes_the_module(client):
    meta = client.get("/api/meta").json()
    module = next(m for m in meta["modules"] if m["key"] == "projects")
    assert module["slug"] == "projets" and module["label"] == ["Projets", "Projects"] and module["icon"] == "FolderKanban"
    assert [(p["slug"], p["entity"]) for p in module["pages"]] == [
        ("projets", "projects.projects"), ("taches", "projects.tasks"), ("temps", "projects.timesheets")]
    assert registry.get("projects").depends == () and registry.get("projects").order == 70

    projects = meta["entities"]["projects.projects"]
    assert projects["label"] == ["Projet", "Project"] and projects["title"] == "name" and projects["board"] == "status"
    fields = {f["name"]: f for f in projects["fields"]}
    assert [n for n, f in fields.items() if f["list"]] == ["code", "name", "client_id", "status", "end_date", "hours_spent",
                                                           "progress", "to_invoice_amount"]
    assert [n for n, f in fields.items() if f["computed"]] == list(FIGURES)
    assert fields["code"]["prefix"] == "PRJ" and fields["code"]["readonly"] and fields["code"]["search"]
    assert fields["name"]["required"] and fields["name"]["search"]
    assert fields["client_id"]["ref"] == "sales.clients" and fields["client_id"]["filter"]
    assert fields["manager_id"]["ref"] == "hr.employees" and fields["manager_id"]["label"][0] == "Chef de projet"
    assert [c["value"] for c in fields["status"]["choices"]] == ["planned", "active", "on_hold", "done", "cancelled"]
    assert [c["label"][0] for c in fields["status"]["choices"]] == ["Prévu", "En cours", "En pause", "Terminé", "Annulé"]
    assert not fields["status"]["readonly"] and fields["status"]["default"] == "planned" and fields["status"]["filter"]
    assert fields["hourly_rate"]["default"] == 65 and fields["hourly_rate"]["label"][0] == "Taux horaire facturé"
    assert fields["budget_hours"]["min"] == 0 and fields["budget_amount"]["type"] == "money"
    assert fields["progress"]["type"] == "percent" and fields["to_invoice_amount"]["type"] == "money"
    [action] = projects["actions"]
    assert (action["key"], action["level"], action["style"]) == ("invoice_time", 2, "primary")
    assert action["label"] == ["Facturer les temps", "Invoice time"] and action["confirm"]

    tasks = meta["entities"]["projects.tasks"]
    assert tasks["title"] == "title" and tasks["board"] == "status" and tasks["plural"] == ["Tâches", "Tasks"]
    fields = {f["name"]: f for f in tasks["fields"]}
    assert [n for n, f in fields.items() if f["list"]] == ["title", "project_id", "assignee_id", "status", "priority",
                                                           "due_date", "spent_hours", "overdue"]
    assert fields["project_id"]["required"] and fields["project_id"]["ref"] == "projects.projects"
    assert [c["value"] for c in fields["status"]["choices"]] == ["todo", "in_progress", "done"]
    assert [c["label"][0] for c in fields["priority"]["choices"]] == ["Basse", "Normale", "Haute", "Urgente"]
    assert fields["priority"]["default"] == "normal" and fields["overdue"]["type"] == "bool" and fields["overdue"]["computed"]
    assert [(a["key"], a["level"]) for a in tasks["actions"]] == [("start", 2), ("finish", 2)]

    timesheets = meta["entities"]["projects.timesheets"]
    assert timesheets["label"] == ["Temps passé", "Time entry"] and timesheets["board"] is None
    fields = {f["name"]: f for f in timesheets["fields"]}
    assert [n for n, f in fields.items() if f["list"]] == ["date", "project_id", "employee_id", "hours", "description",
                                                           "billable", "amount", "invoiced"]
    assert fields["date"]["default"] == _day() and fields["date"]["required"]
    assert fields["hours"]["required"] and fields["hours"]["max"] == 24
    assert fields["billable"]["default"] is True and fields["billable"]["filter"]
    assert fields["task_id"]["ref"] == "projects.tasks" and fields["employee_id"]["ref"] == "hr.employees"
    assert "invoice_id" not in fields and "billed_rate" not in fields  # lus avec la fiche, jamais affichés
    assert timesheets["actions"] == [] and timesheets["can_delete"]


# ═════════════════════════════════════════════════════════════════════════
# Chiffres clés, « Mes vues », vue en colonnes, export
# ═════════════════════════════════════════════════════════════════════════
def test_home_kpis_follow_the_projects(client):
    def kpis():
        return {k["key"]: k for k in client.get("/api/home").json()["kpis"]}

    start = kpis()
    assert start["projects.active_projects"]["path"] == "/projets/projets?f_status=active"
    assert start["projects.hours_month"]["path"] == "/projets/temps"
    assert start["projects.time_to_invoice"]["path"] == "/projets/projets"
    assert start["projects.time_to_invoice"]["unit"] == "money" and start["projects.hours_month"]["unit"] == "count"
    shortcut = next(s for s in client.get("/api/home").json()["shortcuts"] if s["key"] == "projects.new_timesheet")
    assert shortcut["path"] == "/projets/temps?new=1" and shortcut["label"] == ["Saisir du temps", "Log time"]

    project = _project(client, "Projet du mois", client_id=_client("Pixel & Co"), status="active")
    task = _task(client, project, "Conception")
    _act(client, "tasks", _task(client, project, "Terminée d'avance"), "finish")
    _time(client, project, 2.5, task)
    _time(client, project, 1, task, billable=False)
    _project(client, "Projet en pause", status="on_hold")
    now = kpis()
    assert now["projects.active_projects"]["value"] == start["projects.active_projects"]["value"] + 1
    assert now["projects.active_projects"]["count"] == start["projects.active_projects"]["count"] + 1  # tâche ouverte
    assert now["projects.hours_month"]["value"] == pytest.approx(start["projects.hours_month"]["value"] + 3.5)
    assert now["projects.hours_month"]["count"] == start["projects.hours_month"]["count"] + 2
    assert now["projects.time_to_invoice"]["value"] == pytest.approx(start["projects.time_to_invoice"]["value"] + 162.5)
    assert now["projects.time_to_invoice"]["count"] == start["projects.time_to_invoice"]["count"] + 1
    _act(client, "projects", project, "invoice_time")
    end = kpis()
    assert end["projects.time_to_invoice"]["value"] == pytest.approx(start["projects.time_to_invoice"]["value"])
    assert end["projects.time_to_invoice"]["count"] == start["projects.time_to_invoice"]["count"]
    assert end["projects.hours_month"]["value"] == now["projects.hours_month"]["value"]  # facturé ou non, le temps compte
    # chaque chiffre clé correspond à la liste qu'il ouvre
    active = client.get(f"{BASE}/projects", params={"f_status": "active", "size": 200}).json()
    assert end["projects.active_projects"]["value"] == active["total"]
    rows = client.get(f"{BASE}/projects", params={"size": 200}).json()["rows"]
    assert end["projects.time_to_invoice"]["value"] == pytest.approx(sum(r["to_invoice_amount"] for r in rows))
    assert end["projects.time_to_invoice"]["count"] == len([r for r in rows if r["to_invoice_hours"]])


def test_kpis_are_offered_in_my_views(client):
    """« Mes vues » reconnaît un chiffre clé quand la demande cite son libellé : chaque libellé nomme ce qu'il compte,
    et les demandes sur d'autres sujets ne font pas apparaître les projets."""
    def metrics(text):
        widgets = dashboard.compose_offline(text, {})["spec"]["widgets"]
        return [w["params"]["metric"] for w in widgets if w["source"] == "kpi"]

    def sources(text):
        return [w["source"] for w in dashboard.compose_offline(text, {})["spec"]["widgets"]]

    module = registry.get("projects")
    assert [k.key for k in module.kpis] == ["active_projects", "hours_month", "time_to_invoice"]
    for kpi in module.kpis:
        for label in kpi.label:
            assert f"projects.{kpi.key}" in metrics(f"Montre-moi : {label.lower()}"), label
    for text in ("mes factures en retard", "combien j'ai encaissé ce mois-ci", "le temps gagné", "mes commandes en cours",
                 "mes projets", "les tâches en retard", "mon chiffre d'affaires"):
        assert not [m for m in metrics(text) if m.startswith("projects.")], text
    # « facturer » appartient au libellé : pas aussi le graphique du chiffre d'affaires
    assert sources("Temps à facturer") == ["kpi"]
    assert sources("Temps à facturer et factures en retard") == ["kpi", "unpaid_invoices"]
    # de bout en bout : la demande devient une carte, calculée par le module
    res = client.post("/api/dashboards/compose", json={"text": "Montre-moi les projets en cours"})
    [card] = [w for w in res.json()["view"]["widgets"] if w["source"] == "kpi"]
    active = client.get(f"{BASE}/projects", params={"f_status": "active"}).json()["total"]
    assert card["params"]["metric"] == "projects.active_projects" and card["data"]["value"] == active
    assert card["data"]["path"] == "/projets/projets?f_status=active"
    view = client.post("/api/dashboards/render", json={"spec": {"widgets": [
        {"source": "kpi", "params": {"metric": "projects.time_to_invoice"}}]}}).json()["widgets"][0]["data"]
    assert view["unit"] == "money" and view["label"] == ["Temps à facturer", "Time to invoice"]
    # sans accès aux projets, ni la demande ni une vue enregistrée ne montrent ces chiffres
    make_member("commercial-vues-projets@test.local", "sales")
    seller = login_as("commercial-vues-projets@test.local")
    res = seller.post("/api/dashboards/compose", json={"text": "Montre-moi les projets en cours"}).json()
    assert not [w for w in res["view"]["widgets"] if w["params"].get("metric", "").startswith("projects.")]
    hidden = seller.post("/api/dashboards/render", json={"spec": {"widgets": [
        {"source": "kpi", "params": {"metric": "projects.hours_month"}}]}}).json()
    assert hidden["widgets"] == [] and hidden["hidden"] == 1


def test_board_and_export(client):
    board = client.get(f"{BASE}/projects/board").json()
    assert [c["value"] for c in board["columns"]] == ["planned", "active", "on_hold", "done", "cancelled"]
    assert board["field"] == "status" and board["amount_field"] == "to_invoice_amount"
    rows = client.get(f"{BASE}/projects", params={"size": 200}).json()["rows"]
    for column in board["columns"]:
        mine = [r for r in rows if r["status"] == column["value"]]
        assert column["count"] == len(mine) and {r["id"] for r in column["rows"]} == {r["id"] for r in mine}
        assert column["amount"] == pytest.approx(sum(r["to_invoice_amount"] for r in mine))
    tasks = client.get(f"{BASE}/tasks/board").json()
    assert [c["value"] for c in tasks["columns"]] == ["todo", "in_progress", "done"] and tasks["amount_field"] is None
    assert sum(c["count"] for c in tasks["columns"]) == client.get(f"{BASE}/tasks").json()["total"]
    assert client.get(f"{BASE}/timesheets/board").status_code == 404  # pas de vue en colonnes

    project = _project(client, "Rapport annuel Kairos", client_id=_client("Kairos Conseil"), budget_hours=10, status="active")
    _time(client, project, 2.5, _task(client, project, "Mise en page"))
    res = client.get(f"{BASE}/projects/export", params={"q": "Rapport annuel"})
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    header, *lines = list(csv.reader(io.StringIO(res.text.lstrip("﻿")), delimiter=";"))
    [line] = lines
    cells = dict(zip(header, line, strict=True))
    assert cells["Numéro"] == project["code"] and cells["Client"] == "Kairos Conseil" and cells["Statut"] == "En cours"
    assert (cells["Heures passées"], cells["Avancement"], cells["Montant à facturer HT"]) == ("2,5", "25", "162,50")
    assert cells["Taux horaire facturé"] == "65,00"
    english = client.get(f"{BASE}/projects/export", params={"q": "Rapport annuel", "lang": "en"}).text.lstrip("﻿")
    header, line = list(csv.reader(io.StringIO(english)))
    assert dict(zip(header, line, strict=True))["Amount to invoice excl. VAT"] == "162.50"
    times = client.get(f"{BASE}/timesheets/export", params={"f_project_id": project["id"]}).text.lstrip("﻿")
    header, line = list(csv.reader(io.StringIO(times), delimiter=";"))
    cells = dict(zip(header, line, strict=True))
    assert (cells["Heures"], cells["Facturable"], cells["Montant HT"], cells["Facturé"]) == ("2,5", "Oui", "162,50", "Non")
    assert "Facture (identifiant)" not in cells and "Taux facturé" not in cells


# ═════════════════════════════════════════════════════════════════════════
# Démonstration
# ═════════════════════════════════════════════════════════════════════════
def test_demo_data(client):
    projects = {r["name"]: r for r in client.get(f"{BASE}/projects", params={"size": 200}).json()["rows"]}
    assert {NOVA, LEMOINE, KAIROS} <= set(projects)
    nova, lemoine, kairos = projects[NOVA], projects[LEMOINE], projects[KAIROS]
    assert [(p["client_id__label"], p["status"]) for p in (nova, lemoine, kairos)] == [
        ("Atelier Nova", "active"), ("Boulangerie Lemoine", "active"), ("Kairos Conseil", "done")]
    assert nova["hourly_rate"] == 65 and nova["budget_hours"] == 40 and nova["manager_id__label"] == "Camille Roux"
    # 16 h passées sur 40 h dont 15 h facturables ; 10,5 h à 60 €/h ; 6 h dont 5,5 h facturables
    assert {k: nova[k] for k in FIGURES} == {"hours_spent": 16, "progress": 40, "remaining_hours": 24, "tasks_open": 2,
                                             "to_invoice_hours": 15, "to_invoice_amount": 975}
    assert (lemoine["hours_spent"], lemoine["to_invoice_amount"], lemoine["tasks_open"]) == (10.5, 630, 2)
    assert (kairos["hours_spent"], kairos["to_invoice_amount"], kairos["tasks_open"]) == (6, 357.5, 0)
    assert all(p["code"].startswith(f"PRJ-{today().year}-") for p in (nova, lemoine, kairos))

    tasks = {r["title"]: r for r in client.get(f"{BASE}/tasks", params={"size": 200}).json()["rows"]}
    assert [tasks[t]["status"] for t in ("Audit de marque", "Pistes créatives", "Charte graphique")] == ["done", "in_progress",
                                                                                                         "todo"]
    assert tasks["Charte graphique"]["due_date"] == _day(10) and tasks["Charte graphique"]["project_id"] == nova["id"]
    assert tasks["Maquettes des pages"]["overdue"] is True and tasks["Audit de marque"]["overdue"] is False
    assert tasks["Pistes créatives"]["spent_hours"] == 9.5

    entries = client.get(f"{BASE}/timesheets", params={"size": 200}).json()["rows"]
    demo = [e for e in entries if e["project_id"] in {nova["id"], lemoine["id"], kairos["id"]}]
    assert len(demo) >= 10 and len([e for e in demo if e["billable"]]) > len(demo) / 2
    assert not [e for e in demo if e["invoiced"] or e["invoice_id"]]  # rien n'est facturé
    assert all(_day(-30) <= e["date"] <= _day() for e in demo)  # trois semaines, en jours ouvrés
    assert {e["employee_id__label"] for e in demo} <= {"Alex Durand", "Camille Roux", "Hugo Martin", "Léa Bernard",
                                                       "Nina Lefèvre"}
    assert all(e["task_id"] is None or e["task_id__label"] for e in demo)
    # la démonstration ne crée aucune facture
    assert not db.fetch_one("SELECT COUNT(*) AS n FROM invoices WHERE title LIKE 'Projet %'")["n"]
    kpis = {k["key"]: k for k in client.get("/api/home").json()["kpis"]}
    assert kpis["projects.active_projects"]["value"] >= 2
    assert kpis["projects.time_to_invoice"]["value"] >= 1962.5 and kpis["projects.time_to_invoice"]["count"] >= 3
