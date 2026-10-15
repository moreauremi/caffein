# SPDX-License-Identifier: AGPL-3.0-or-later
"""RH : salariés, services, absences (jours ouvrés, jours fériés, soldes de congés), notes de frais, droits."""

from datetime import date, timedelta

import pytest

from caffein import db, services
from caffein.core import modules as registry
from caffein.modules.hr import services as hr
from caffein.modules.hr import workdays
from caffein.utils import today

from .helpers import disable_module, login_as, make_member

BASE = "/api/data/hr"


@pytest.fixture()
def restore_modules():
    yield
    registry.enable_all()


def _department(name: str) -> int:
    return db.fetch_one("SELECT id FROM hr_departments WHERE name = ?", (name,))["id"]


def _employee_id(full_name: str) -> int:
    return db.fetch_one("SELECT id FROM hr_employees WHERE full_name = ?", (full_name,))["id"]


def _new_employee(client, **data) -> dict:
    res = client.post(f"{BASE}/employees", json={"first_name": "Jeanne", "last_name": "Essai", **data})
    assert res.status_code == 201, res.text
    return res.json()


def _absence(client, employee_id: int, start, end, kind: str = "paid_leave", **data):
    return client.post(f"{BASE}/absences", json={"employee_id": employee_id, "kind": kind, "start_date": str(start),
                                                  "end_date": str(end), **data})


def _approved(client, employee_id: int, start, end, kind: str = "rtt") -> dict:
    res = _absence(client, employee_id, start, end, kind)
    assert res.status_code == 201, res.text
    approved = client.post(f"{BASE}/absences/{res.json()['id']}/actions/approve")
    assert approved.status_code == 200, approved.text
    return approved.json()["row"]


def _february_monday(year: int) -> date:
    """Premier lundi à partir du 2 février : les semaines qui suivent n'ont aucun jour férié."""
    start = date(year, 2, 2)
    return start + timedelta(days=(7 - start.weekday()) % 7)


# ═════════════════════════════════════════════════════════════════════════
# Jours ouvrés et jours fériés
# ═════════════════════════════════════════════════════════════════════════
def test_working_days_and_french_public_holidays():
    assert [workdays.easter(y) for y in (2024, 2025, 2026, 2027, 2038, 2285)] == [
        date(2024, 3, 31), date(2025, 4, 20), date(2026, 4, 5), date(2027, 3, 28), date(2038, 4, 25), date(2285, 3, 22)]
    holidays = workdays.public_holidays(2026)
    assert len(holidays) == 11 and holidays[date(2026, 4, 6)] == ("Lundi de Pâques", "Easter Monday")
    assert holidays[date(2026, 5, 14)][0] == "Ascension" and holidays[date(2026, 5, 25)][0] == "Lundi de Pentecôte"
    assert workdays.public_holidays(2027)[date(2027, 5, 6)][0] == "Ascension"            # Pâques 2027 : 28 mars
    assert {date(2026, 1, 1), date(2026, 5, 1), date(2026, 5, 8), date(2026, 7, 14), date(2026, 8, 15), date(2026, 11, 1),
            date(2026, 11, 11), date(2026, 12, 25)} <= set(holidays)
    # du 27 avril au 8 mai 2026 : 10 jours de semaine, dont le 1er et le 8 mai (deux vendredis fériés)
    assert workdays.working_days("2026-04-27", "2026-05-08") == 8
    assert workdays.working_days(date(2026, 5, 11), date(2026, 5, 15)) == 4        # jeudi de l'Ascension
    assert workdays.working_days("2026-05-25", "2026-05-29") == 4                    # lundi de Pentecôte
    assert workdays.working_days("2026-05-16", "2026-05-17") == 0                    # un week-end
    assert workdays.working_days("2026-05-15", "2026-05-11") == 0                    # période vide
    assert workdays.working_days(None, "2026-05-11") == 0
    assert workdays.working_days("2026-12-24", "2027-01-04") == 6                    # Noël et jour de l'an
    # 2026 : 261 jours de semaine, dont 9 fériés (le 15 août et le 1er novembre tombent un week-end)
    assert workdays.working_days("2026-01-01", "2026-12-31") == 252
    start = date(2025, 12, 1)
    for length in range(0, 420, 11):  # le calcul direct donne le décompte jour par jour
        naive = sum(1 for i in range(length + 1) if workdays.is_working_day(start + timedelta(days=i)))
        assert workdays.working_days(start, start + timedelta(days=length)) == naive
    assert workdays.next_working_day(date(2026, 5, 14)) == date(2026, 5, 15)
    assert workdays.next_working_day(date(2026, 5, 23)) == date(2026, 5, 26)        # samedi → mardi de Pentecôte


def test_absence_days_exclude_weekends_and_public_holidays(client):
    employee = _new_employee(client)
    may = _absence(client, employee["id"], "2026-04-27", "2026-05-08", kind="training")
    assert may.status_code == 201, may.text
    count = db.fetch_one("SELECT COUNT(*) AS n FROM hr_absences")["n"]
    assert may.json()["days"] == 8 and may.json()["code"] == f"ABS-{today().year}-{count:04d}"
    assert may.json()["status"] == "requested" and may.json()["employee_id__label"] == "Jeanne Essai"
    assert _absence(client, employee["id"], "2026-05-11", "2026-05-15", kind="training").json()["days"] == 4
    preview = client.post(f"{BASE}/absences/preview", json={"start_date": "2026-05-25", "end_date": "2026-05-29"}).json()
    assert preview["computed"]["days"] == 4
    listing = client.get(f"{BASE}/absences", params={"f_employee_id": employee["id"]}).json()
    assert listing["total"] == 2 and [r["days"] for r in listing["rows"]] == [4, 8]  # les plus récentes d'abord


# ═════════════════════════════════════════════════════════════════════════
# Salariés et services
# ═════════════════════════════════════════════════════════════════════════
def test_employee_record_numbering_and_figures(client):
    creation = _department("Création")
    headcount = client.get(f"{BASE}/departments/{creation}").json()["headcount"]
    res = client.post(f"{BASE}/employees", json={
        "first_name": " Jeanne ", "last_name": "Moreau", "department_id": creation, "job_title": "Graphiste junior",
        "hire_date": (today() - timedelta(days=1096)).isoformat(), "salary": "2 400,50", "email": "jeanne@studio.example",
        "code": "PIRATE", "full_name": "Pirate"})
    assert res.status_code == 201, res.text
    employee = res.json()
    count = db.fetch_one("SELECT COUNT(*) AS n FROM hr_employees")["n"]
    assert employee["code"] == f"MAT-{count:04d}" and employee["full_name"] == "Jeanne Moreau"
    assert (employee["weekly_hours"], employee["annual_leave_days"], employee["contract_type"], employee["active"]) == (35, 25, "cdi", True)
    assert employee["salary"] == 2400.5 and employee["department_id__label"] == "Création"
    assert employee["seniority_years"] == 3.0 and employee["leave_taken"] == 0 and employee["leave_balance"] == 25
    assert client.get(f"{BASE}/departments/{creation}").json()["headcount"] == headcount + 1

    # le nom complet suit chaque changement de prénom ou de nom, et les références avec lui
    url = f"{BASE}/employees/{employee['id']}"
    assert client.put(url, json={"last_name": "Morel"}).json()["full_name"] == "Jeanne Morel"
    renamed = client.put(url, json={"first_name": "Jeanne-Marie", "code": ""}).json()
    assert renamed["full_name"] == "Jeanne-Marie Morel" and renamed["code"] == employee["code"]
    assert client.put(url, json={"job_title": "Graphiste"}).json()["full_name"] == "Jeanne-Marie Morel"
    found = client.get(f"{BASE}/employees", params={"q": "morel"}).json()
    assert found["total"] == 1 and found["rows"][0]["full_name"] == "Jeanne-Marie Morel"
    absence = _absence(client, employee["id"], "2026-06-01", "2026-06-01", kind="training").json()
    assert absence["employee_id__label"] == "Jeanne-Marie Morel"
    options = client.get(f"{BASE}/employees/options", params={"q": "jeanne-marie"}).json()
    assert options == [{"id": employee["id"], "label": "Jeanne-Marie Morel", "sublabel": "Graphiste"}]

    # ancienneté : jusqu'à la date de sortie si elle est passée ; nulle avant l'entrée ; vide sans date d'entrée
    assert client.put(url, json={"hire_date": "2020-01-01", "end_date": "2023-01-01"}).json()["seniority_years"] == 3.0
    future = (today() + timedelta(days=30)).isoformat()
    assert client.put(url, json={"hire_date": future, "end_date": None}).json()["seniority_years"] == 0
    assert client.put(url, json={"hire_date": None}).json()["seniority_years"] is None

    for data, message in [
        ({"hire_date": "2020-01-01", "end_date": "2019-12-31"}, "Date de sortie : elle ne peut pas précéder la date d'entrée."),
        ({"first_name": ""}, "Prénom : obligatoire."),
        ({"last_name": "  "}, "Nom : obligatoire."),
        ({"weekly_hours": 61}, "Heures par semaine : 60 au maximum."),
        ({"weekly_hours": -1}, "Heures par semaine : 0 au minimum."),
        ({"annual_leave_days": -1}, "Congés annuels (jours) : 0 au minimum."),
        ({"annual_leave_days": 61}, "Congés annuels (jours) : 60 au maximum."),
        ({"salary": -1}, "Salaire brut mensuel : 0 au minimum."),
        ({"contract_type": "cdi2"}, "Contrat : valeur non proposée."),
        ({"contract_type": ""}, "Contrat : obligatoire."),
        ({"email": "jeanne"}, "Email : adresse email invalide."),
        ({"phone": "appelez-moi"}, "Téléphone : numéro invalide."),
        ({"hire_date": "2026-13-01"}, "Date d'entrée : date invalide."),
        ({"department_id": 999999}, "Service : fiche introuvable."),
    ]:
        res = client.put(url, json=data)
        assert res.status_code == 400 and res.json()["detail"] == message, data
    assert client.post(f"{BASE}/employees", json={"first_name": "Sans nom"}).json()["detail"] == "Nom : obligatoire."
    # une case « actif » laissée vide ne change rien (la colonne n'accepte pas l'absence de valeur)
    kept = client.put(url, json={"active": None})
    assert kept.status_code == 200 and kept.json()["active"] is True

    # aperçu pendant la saisie : ancienneté et solde calculés par le serveur
    hired = (today() - timedelta(days=731)).isoformat()
    preview = client.post(f"{BASE}/employees/preview", json={"hire_date": hired, "annual_leave_days": "20,5"}).json()
    assert preview["computed"] == {"seniority_years": 2.0, "leave_taken": 0, "leave_balance": 20.5}

    # l'effectif ne compte que les salariés actifs ; la liste filtre sur le contrat et l'état
    client.put(url, json={"active": False})
    assert client.get(f"{BASE}/departments/{creation}").json()["headcount"] == headcount
    interns = client.get(f"{BASE}/employees", params={"f_contract_type": "intern"}).json()
    assert interns["total"] >= 1 and all(r["contract_type"] == "intern" for r in interns["rows"])
    inactive = client.get(f"{BASE}/employees", params={"f_active": "0"}).json()["rows"]
    assert [r["id"] for r in inactive] == [employee["id"]]


def test_departments_and_records_in_use(client):
    assert client.post(f"{BASE}/departments", json={"name": "création"}).json()["detail"] == "Nom : « création » existe déjà."
    assert client.post(f"{BASE}/departments", json={"name": " "}).json()["detail"] == "Nom : obligatoire."
    studio = client.post(f"{BASE}/departments", json={"name": "Studio photo"}).json()
    assert studio["headcount"] == 0 and studio["manager_id"] is None
    assert client.put(f"{BASE}/departments/{studio['id']}", json={"manager_id": 999999}).json()["detail"] == \
        "Responsable : fiche introuvable."
    employee = _new_employee(client, department_id=studio["id"])
    client.put(f"{BASE}/departments/{studio['id']}", json={"manager_id": employee["id"]})
    listing = client.get(f"{BASE}/departments", params={"q": "studio"}).json()["rows"][0]
    assert listing["headcount"] == 1 and listing["manager_id__label"] == "Jeanne Essai"

    res = client.delete(f"{BASE}/departments/{studio['id']}")
    assert res.status_code == 409 and "salariés : 1" in res.json()["detail"]
    res = client.delete(f"{BASE}/employees/{employee['id']}")
    assert res.status_code == 409 and "services : 1" in res.json()["detail"]
    camille = client.delete(f"{BASE}/employees/{_employee_id('Camille Roux')}")
    assert camille.status_code == 409 and "absences : 1" in camille.json()["detail"] and "notes de frais" in camille.json()["detail"]

    client.put(f"{BASE}/departments/{studio['id']}", json={"manager_id": None})
    assert client.delete(f"{BASE}/employees/{employee['id']}").status_code == 204
    assert client.delete(f"{BASE}/departments/{studio['id']}").status_code == 204


# ═════════════════════════════════════════════════════════════════════════
# Absences
# ═════════════════════════════════════════════════════════════════════════
def test_absence_validation(client):
    employee = _new_employee(client)

    def post(**data):
        return client.post(f"{BASE}/absences", json={"employee_id": employee["id"], "kind": "rtt", **data})

    for data, message in [
        ({"start_date": "2026-06-05", "end_date": "2026-06-01"}, "Date de fin : elle ne peut pas précéder la date de début."),
        ({"start_date": "2026-05-16", "end_date": "2026-05-17"},
         "Date de début : la période ne compte aucun jour ouvré (week-end ou jour férié)."),
        ({"start_date": "2026-05-14", "end_date": "2026-05-14"},
         "Date de début : la période ne compte aucun jour ouvré (week-end ou jour férié)."),
        ({"start_date": "2026-06-01"}, "Date de fin : obligatoire."),
        ({"start_date": "2026-02-30", "end_date": "2026-03-02"}, "Date de début : date invalide."),
        ({"start_date": "2026-06-01", "end_date": "2026-06-01", "kind": "vacances"}, "Type : valeur non proposée."),
        ({"start_date": "2026-06-01", "end_date": "2026-06-01", "employee_id": None}, "Salarié : obligatoire."),
        ({"start_date": "2026-06-01", "end_date": "2026-06-01", "employee_id": 999999}, "Salarié : fiche introuvable."),
    ]:
        res = post(**data)
        assert res.status_code == 400 and res.json()["detail"] == message, data
    created = post(start_date="2026-06-01", end_date="2026-06-05", status="approved", decided_on="2026-01-01").json()
    assert created["status"] == "requested" and created["decided_on"] is None  # champs remplis par le serveur
    # début par défaut : aujourd'hui
    other = _new_employee(client, first_name="Paul")
    default = client.post(f"{BASE}/absences", json={"employee_id": other["id"], "kind": "rtt",
                                                    "end_date": workdays.next_working_day(today()).isoformat()}).json()
    assert default["start_date"] == today().isoformat() and default["days"] == 1


def test_absences_cannot_overlap(client):
    employee, colleague = _new_employee(client), _new_employee(client, first_name="Paul")
    first = _absence(client, employee["id"], "2026-06-01", "2026-06-05", kind="rtt").json()
    res = _absence(client, employee["id"], "2026-06-04", "2026-06-10", kind="sick")
    assert res.status_code == 400
    assert res.json()["detail"] == ("Date de début : la période chevauche une autre absence du salarié "
                                    "(du 01/06/2026 au 05/06/2026).")
    assert _absence(client, colleague["id"], "2026-06-04", "2026-06-10", kind="rtt").status_code == 201  # un autre salarié
    second = _absence(client, employee["id"], "2026-06-08", "2026-06-12", kind="rtt")
    assert second.status_code == 201                                                  # période voisine
    # la fiche elle-même ne se chevauche pas ; l'allonger sur la demande suivante, si
    url = f"{BASE}/absences/{first['id']}"
    assert client.put(url, json={"reason": "Pont"}).status_code == 200
    assert client.put(url, json={"end_date": "2026-06-09"}).status_code == 400
    # une absence annulée ou refusée libère sa période
    client.post(f"{BASE}/absences/{second.json()['id']}/actions/cancel")
    extended = client.put(url, json={"end_date": "2026-06-09"})
    assert extended.status_code == 200 and extended.json()["days"] == 7
    third = _absence(client, employee["id"], "2026-06-15", "2026-06-19", kind="rtt").json()
    client.post(f"{BASE}/absences/{third['id']}/actions/refuse")
    assert _absence(client, employee["id"], "2026-06-17", "2026-06-17", kind="sick").status_code == 201
    # une absence validée bloque aussi sa période
    client.post(f"{url}/actions/approve")
    assert _absence(client, employee["id"], "2026-06-09", "2026-06-09", kind="training").status_code == 400


def test_paid_leave_balance(client):
    year = today().year
    monday = _february_monday(year)
    employee = _new_employee(client, annual_leave_days=7)
    assert employee["leave_taken"] == 0 and employee["leave_balance"] == 7
    leave = _approved(client, employee["id"], monday, monday + timedelta(days=4), kind="paid_leave")
    assert leave["days"] == 5
    record = client.get(f"{BASE}/employees/{employee['id']}").json()
    assert record["leave_taken"] == 5 and record["leave_balance"] == 2
    row = next(r for r in client.get(f"{BASE}/employees", params={"size": 200}).json()["rows"] if r["id"] == employee["id"])
    assert (row["leave_taken"], row["leave_balance"]) == (5, 2)                     # liste : requête groupée
    assert hr.leave_balance(employee["id"]) == 2 and hr.leave_balance(999999) is None

    # plus de jours que le solde : refusé ; les autres types d'absence ne consomment pas de congés payés
    week = monday + timedelta(days=28)
    res = _absence(client, employee["id"], week, week + timedelta(days=4))
    assert res.status_code == 400 and res.json()["detail"] == "Solde de congés insuffisant : il reste 2 jour(s)."
    assert _absence(client, employee["id"], week, week + timedelta(days=4), kind="rtt").status_code == 201

    # deux demandes dans le solde, mais pas ensemble : la seconde validation est refusée
    first = _absence(client, employee["id"], monday + timedelta(days=14), monday + timedelta(days=15)).json()
    second = _absence(client, employee["id"], monday + timedelta(days=21), monday + timedelta(days=22)).json()
    assert first["days"] == second["days"] == 2
    assert client.post(f"{BASE}/absences/{first['id']}/actions/approve").status_code == 200
    res = client.post(f"{BASE}/absences/{second['id']}/actions/approve")
    assert res.status_code == 400 and res.json()["detail"] == "Solde de congés insuffisant : il reste 0 jour(s)."
    assert client.get(f"{BASE}/absences/{second['id']}").json()["status"] == "requested"
    assert client.get(f"{BASE}/employees/{employee['id']}").json()["leave_balance"] == 0

    # à cheval sur deux années : chaque année se décompte sur son propre solde
    newcomer = _new_employee(client, first_name="Lina", annual_leave_days=4)
    res = _absence(client, newcomer["id"], "2026-12-28", "2027-01-08")
    assert res.status_code == 400 and res.json()["detail"] == "Solde de congés insuffisant : il reste 4 jour(s) en 2027."
    client.put(f"{BASE}/employees/{newcomer['id']}", json={"annual_leave_days": 5})
    winter = _absence(client, newcomer["id"], "2026-12-28", "2027-01-08")
    assert winter.status_code == 201 and winter.json()["days"] == 9                # 4 jours en 2026, 5 en 2027
    assert client.post(f"{BASE}/absences/{winter.json()['id']}/actions/approve").status_code == 200
    assert (hr.leave_balance(newcomer["id"], 2026), hr.leave_balance(newcomer["id"], 2027)) == (1, 0)
    # sans droits à congés, pas de congés payés
    intern = _new_employee(client, first_name="Théo", annual_leave_days=None)
    res = _absence(client, intern["id"], "2026-06-01", "2026-06-01")
    assert res.status_code == 400 and res.json()["detail"] == "Solde de congés insuffisant : il reste 0 jour(s)."


def test_absence_workflow_and_locking(client):
    employee = _new_employee(client)
    absence = _absence(client, employee["id"], "2026-06-01", "2026-06-05", kind="rtt").json()
    assert absence["_locked"] is None and absence["_actions"] == ["approve", "refuse", "cancel"]
    url = f"{BASE}/absences/{absence['id']}"
    approved = client.post(f"{url}/actions/approve").json()
    assert approved["message"] == f"Absence {absence['code']} validée : 5 jour(s) ouvré(s)."
    row = approved["row"]
    assert row["status"] == "approved" and row["decided_on"] == today().isoformat()
    assert row["_actions"] == ["cancel"] and row["_locked"].startswith("Absence validée")
    assert client.put(url, json={"reason": "Modifiée"}).status_code == 409
    assert client.delete(url).status_code == 409
    assert client.post(f"{url}/actions/approve").status_code == 409
    assert client.post(f"{url}/actions/refuse").status_code == 409
    assert client.post(f"{url}/actions/nope").status_code == 404
    cancelled = client.post(f"{url}/actions/cancel").json()
    assert cancelled["row"]["status"] == "cancelled" and cancelled["row"]["_actions"] == []
    assert cancelled["message"] == f"Absence {absence['code']} annulée."
    assert client.post(f"{url}/actions/cancel").status_code == 409

    refused = _absence(client, employee["id"], "2026-06-08", "2026-06-08", kind="rtt").json()
    result = client.post(f"{BASE}/absences/{refused['id']}/actions/refuse").json()
    assert result["row"]["status"] == "refused" and result["row"]["decided_on"] == today().isoformat()
    assert result["row"]["_locked"] == "Demande refusée : elle ne se modifie plus."
    assert client.post(f"{BASE}/absences/{refused['id']}/actions/cancel").status_code == 409

    pending = _absence(client, employee["id"], "2026-06-15", "2026-06-15", kind="rtt").json()
    assert client.delete(f"{BASE}/absences/{pending['id']}").status_code == 204


# ═════════════════════════════════════════════════════════════════════════
# Notes de frais
# ═════════════════════════════════════════════════════════════════════════
LINES = [
    {"date": "2026-10-01", "category": "transport", "description": "Train Lyon – Marseille", "amount": "86,40", "vat": 7.85},
    {"date": "2026-10-01", "category": "meals", "description": "Déjeuner", "amount": 18.7, "vat": 1.7},
    {"date": "2026-10-02", "category": "mileage", "description": "Trajet en voiture, 42 km", "amount": 26.71},
]


def test_expense_report_totals_and_validation(client):
    employee = _new_employee(client, first_name="Élise", last_name="Fabre")
    res = client.post(f"{BASE}/expenses", json={"employee_id": employee["id"], "title": "Rendez-vous Maison Verde", "lines": LINES,
                                                 "code": "PIRATE", "status": "paid", "paid_on": "2026-01-01"})
    assert res.status_code == 201, res.text
    report = res.json()
    count = db.fetch_one("SELECT COUNT(*) AS n FROM hr_expenses")["n"]
    assert report["code"] == f"NDF-{today().year}-{count:04d}" and report["status"] == "draft" and report["paid_on"] is None
    assert report["total"] == 131.81 and report["total_vat"] == 9.55 and report["lines"][2]["vat"] == 0
    assert report["date"] == today().isoformat() and report["_actions"] == ["submit"] and report["_locked"] is None
    row = client.get(f"{BASE}/expenses", params={"f_employee_id": employee["id"]}).json()["rows"][0]
    assert (row["total"], row["total_vat"]) == (131.81, 9.55)                        # liste : requête groupée
    preview = client.post(f"{BASE}/expenses/preview", json={"lines": [{"amount": "10,50", "vat": 1.75}, {"amount": "x"}]}).json()
    assert preview["computed"] == {"total": 10.5, "total_vat": 1.75}

    def line(**data):
        return [{"date": "2026-10-01", "category": "meals", "description": "Repas", "amount": 20, **data}]

    for lines, message in [
        (line(vat=20.01), "Dépenses, ligne 1 — Dont TVA : elle ne peut pas dépasser le montant TTC."),
        (line(vat=-1), "Dépenses, ligne 1 — Dont TVA : 0 au minimum."),
        (line(category="mileage", vat=1), "Dépenses, ligne 1 — Dont TVA : les indemnités kilométriques ne comportent pas de TVA."),
        (line(amount=-5), "Dépenses, ligne 1 — Montant TTC : 0 au minimum."),
        (line(amount=None), "Dépenses, ligne 1 — Montant TTC : obligatoire."),
        (line(description=""), "Dépenses, ligne 1 — Description : obligatoire."),
        (line(date=None), "Dépenses, ligne 1 — Date : obligatoire."),
        (line(category="cadeaux"), "Dépenses, ligne 1 — Catégorie : valeur non proposée."),
    ]:
        res = client.put(f"{BASE}/expenses/{report['id']}", json={"lines": lines})
        assert res.status_code == 400 and res.json()["detail"] == message, lines
    assert client.post(f"{BASE}/expenses", json={"employee_id": employee["id"]}).json()["detail"] == "Objet : obligatoire."
    assert client.post(f"{BASE}/expenses", json={"title": "Sans salarié"}).json()["detail"] == "Salarié : obligatoire."

    # une note vide ou nulle ne se soumet pas
    empty = client.post(f"{BASE}/expenses", json={"employee_id": employee["id"], "title": "Vide"}).json()
    res = client.post(f"{BASE}/expenses/{empty['id']}/actions/submit")
    assert res.status_code == 400 and res.json()["detail"].startswith("Dépenses : ajoutez au moins une dépense")
    client.put(f"{BASE}/expenses/{empty['id']}", json={"lines": line(amount=0)})
    res = client.post(f"{BASE}/expenses/{empty['id']}/actions/submit")
    assert res.status_code == 400 and "total de la note de frais est nul" in res.json()["detail"]
    assert client.delete(f"{BASE}/expenses/{empty['id']}").status_code == 204


def test_expense_report_workflow_records_receipt(client):
    employee = _new_employee(client, first_name="Élise", last_name="Fabre")
    title = "Déplacement chez Maison Verde à Marseille pour le shooting des produits"
    report = client.post(f"{BASE}/expenses", json={"employee_id": employee["id"], "title": title, "lines": LINES}).json()
    url = f"{BASE}/expenses/{report['id']}"
    assert client.post(f"{url}/actions/approve").status_code == 409                 # pas encore soumise
    submitted = client.post(f"{url}/actions/submit").json()
    assert submitted["message"] == f"Note de frais {report['code']} soumise pour validation."
    assert submitted["row"]["status"] == "submitted" and submitted["row"]["_actions"] == ["approve", "refuse"]
    assert submitted["row"]["_locked"].startswith("Note de frais soumise")
    assert client.put(url, json={"title": "Autre"}).status_code == 409
    assert client.delete(url).status_code == 409
    for action in ("submit", "pay"):
        assert client.post(f"{url}/actions/{action}").status_code == 409
    approved = client.post(f"{url}/actions/approve").json()["row"]
    assert approved["status"] == "approved" and approved["_actions"] == ["pay"]
    assert client.post(f"{url}/actions/refuse").status_code == 409

    documents = len(services.list_documents())
    paid = client.post(f"{url}/actions/pay").json()
    assert paid["row"]["status"] == "paid" and paid["row"]["paid_on"] == today().isoformat() and paid["row"]["_actions"] == []
    assert "comptabilité" in paid["message"] and paid["message"].startswith(f"Note de frais {report['code']} remboursée")
    assert len(services.list_documents()) == documents + 1
    receipt = next(d for d in services.list_documents() if d["source"] == "expense")
    assert receipt["fournisseur"] == "NOTE DE FRAIS ÉLISE FABRE" and receipt["resume"] == title[:50]
    assert (receipt["ht"], receipt["tva"], receipt["ttc"]) == (122.26, 9.55, 131.81)
    assert receipt["categorie"] == "Frais de déplacement" and receipt["tva_type"] == "deductible"
    assert receipt["date"] == today().isoformat() and receipt["extracted_by"] == "caffein"
    assert client.post(f"{url}/actions/pay").status_code == 409                      # une seule fois

    refused = client.post(f"{BASE}/expenses", json={"employee_id": employee["id"], "title": "Taxi", "lines": LINES[:1]}).json()
    client.post(f"{BASE}/expenses/{refused['id']}/actions/submit")
    result = client.post(f"{BASE}/expenses/{refused['id']}/actions/refuse").json()
    assert result["row"]["status"] == "refused" and result["row"]["_actions"] == []
    assert result["message"] == f"Note de frais {refused['code']} refusée."
    for action in ("approve", "pay", "submit"):
        assert client.post(f"{BASE}/expenses/{refused['id']}/actions/{action}").status_code == 409


def test_expense_paid_without_accounting(client, restore_modules):
    employee = _new_employee(client)
    report = client.post(f"{BASE}/expenses", json={"employee_id": employee["id"], "title": "Fournitures", "lines": LINES}).json()
    url = f"{BASE}/expenses/{report['id']}/actions"
    client.post(f"{url}/submit")
    client.post(f"{url}/approve")
    documents = db.fetch_one("SELECT COUNT(*) AS n FROM documents")["n"]
    disable_module(client, "accounting")
    paid = client.post(f"{url}/pay").json()
    assert paid["row"]["status"] == "paid" and paid["message"] == f"Note de frais {report['code']} remboursée (131,81 €)."
    assert db.fetch_one("SELECT COUNT(*) AS n FROM documents")["n"] == documents


# ═════════════════════════════════════════════════════════════════════════
# Droits
# ═════════════════════════════════════════════════════════════════════════
def test_rights_salaries_and_approvals(client):
    employee = _new_employee(client, salary=3100)
    soon = today() + timedelta(days=60)

    # Lecture seule : consultation, sans salaire ni modification
    make_member("lecture.rh@test.local", "readonly")
    reader = login_as("lecture.rh@test.local")
    rows = reader.get(f"{BASE}/employees").json()["rows"]
    assert rows and all("salary" not in r for r in rows)
    assert reader.get(f"{BASE}/employees", params={"sort": "salary"}).status_code == 200  # tri ignoré, rien ne fuit
    assert _absence(reader, employee["id"], soon, soon, kind="rtt").status_code == 403
    assert reader.post(f"{BASE}/expenses", json={"employee_id": employee["id"], "title": "x"}).status_code == 403
    assert reader.put(f"{BASE}/employees/{employee['id']}", json={"job_title": "x"}).status_code == 403
    lea_rtt = db.fetch_one("SELECT id FROM hr_absences WHERE status = 'requested'")["id"]
    assert reader.post(f"{BASE}/absences/{lea_rtt}/actions/cancel").status_code == 403
    draft = db.fetch_one("SELECT id FROM hr_expenses WHERE status = 'draft'")["id"]
    assert reader.post(f"{BASE}/expenses/{draft}/actions/submit").status_code == 403

    # Équipe (écriture sur tous les modules) : demande et annule, ne valide pas ; salaire masqué et intouchable
    make_member("equipe.rh@test.local", "team")
    member = login_as("equipe.rh@test.local")
    meta = member.get("/api/meta").json()["entities"]["hr.employees"]
    assert "salary" not in [f["name"] for f in meta["fields"]] and meta["can_create"] and not meta["can_delete"]
    record = member.get(f"{BASE}/employees/{employee['id']}").json()
    assert "salary" not in record and record["full_name"] == "Jeanne Essai"
    assert member.put(f"{BASE}/employees/{employee['id']}", json={"salary": 9999, "job_title": "Graphiste"}).status_code == 200
    admin_view = client.get(f"{BASE}/employees/{employee['id']}").json()
    assert admin_view["salary"] == 3100 and admin_view["job_title"] == "Graphiste"
    hired = member.post(f"{BASE}/employees", json={"first_name": "Marc", "last_name": "Blanc", "salary": 5000}).json()
    assert db.fetch_one("SELECT salary FROM hr_employees WHERE id = ?", (hired["id"],))["salary"] is None
    assert member.delete(f"{BASE}/employees/{hired['id']}").status_code == 403             # suppression : gestion
    request = _absence(member, employee["id"], soon, soon + timedelta(days=4), kind="rtt").json()
    assert request["_actions"] == ["cancel"]
    for action in ("approve", "refuse"):
        res = member.post(f"{BASE}/absences/{request['id']}/actions/{action}")
        assert res.status_code == 403, action
    assert member.delete(f"{BASE}/absences/{request['id']}").status_code == 403
    assert member.post(f"{BASE}/absences/{request['id']}/actions/cancel").json()["row"]["status"] == "cancelled"

    # Une absence validée se décommande au niveau écriture tant qu'elle n'a pas commencé ; ensuite, gestion seulement
    later = _approved(client, employee["id"], today() + timedelta(days=30), today() + timedelta(days=34))
    assert member.post(f"{BASE}/absences/{later['id']}/actions/cancel").json()["row"]["status"] == "cancelled"
    ongoing = _approved(client, employee["id"], today() - timedelta(days=3), today() + timedelta(days=3))
    res = member.post(f"{BASE}/absences/{ongoing['id']}/actions/cancel")
    assert res.status_code == 403 and "seul un responsable" in res.json()["detail"]
    assert client.post(f"{BASE}/absences/{ongoing['id']}/actions/cancel").json()["row"]["status"] == "cancelled"

    # Notes de frais : l'équipe saisit et soumet ; la validation et le remboursement sont réservés à la gestion
    report = member.post(f"{BASE}/expenses", json={"employee_id": employee["id"], "title": "Taxi", "lines": LINES[:1]}).json()
    assert member.post(f"{BASE}/expenses/{report['id']}/actions/submit").status_code == 200
    assert member.post(f"{BASE}/expenses/{report['id']}/actions/approve").status_code == 403
    client.post(f"{BASE}/expenses/{report['id']}/actions/approve")
    assert member.post(f"{BASE}/expenses/{report['id']}/actions/pay").status_code == 403

    # Dérogation au niveau écriture : pas de validation
    make_member("derogation.rh@test.local", "readonly", {"hr": "write"})
    writer = login_as("derogation.rh@test.local")
    day = workdays.next_working_day(soon + timedelta(days=7))
    pending = _absence(writer, employee["id"], day, day, kind="rtt").json()
    assert writer.post(f"{BASE}/absences/{pending['id']}/actions/approve").status_code == 403

    # Rôle « Ressources humaines » (gestion) : salaires visibles, validations possibles
    make_member("rh@test.local", "hr")
    manager = login_as("rh@test.local")
    assert manager.get(f"{BASE}/employees/{employee['id']}").json()["salary"] == 3100
    assert "salary" in [f["name"] for f in manager.get("/api/meta").json()["entities"]["hr.employees"]["fields"]]
    assert manager.post(f"{BASE}/absences/{pending['id']}/actions/approve").json()["row"]["status"] == "approved"
    assert manager.put(f"{BASE}/employees/{employee['id']}", json={"salary": 3200}).json()["salary"] == 3200


def test_export_hides_salaries_below_manage(client):
    _new_employee(client, salary=3100)

    def export(c) -> list[str]:
        res = c.get(f"{BASE}/employees/export")
        assert res.status_code == 200, res.text
        return res.content.decode("utf-8-sig").splitlines()

    lines = export(client)
    assert "Salaire brut mensuel" in lines[0].split(";") and "Solde de congés (jours)" in lines[0].split(";")
    assert "3100,00" in next(line for line in lines if "Jeanne Essai" in line).split(";")
    make_member("export.rh@test.local", "team")
    lines = export(login_as("export.rh@test.local"))
    assert "Salaire brut mensuel" not in lines[0] and "Nom complet" in lines[0].split(";")
    assert "3100,00" not in next(line for line in lines if "Jeanne Essai" in line)


# ═════════════════════════════════════════════════════════════════════════
# Accueil, description de l'espace, désactivation, démonstration, services
# ═════════════════════════════════════════════════════════════════════════
def test_kpis_and_shortcut(client):
    def kpis() -> dict:
        return {k["key"]: k for k in client.get("/api/home").json()["kpis"] if k["module"] == "hr"}

    figures = kpis()
    assert set(figures) == {"hr.headcount", "hr.absent_today", "hr.to_approve"}
    assert {k: tuple(v["label"]) for k, v in figures.items()} == {
        "hr.headcount": ("Effectif salarié", "Employee headcount"),
        "hr.absent_today": ("Salariés absents aujourd'hui", "Employees absent today"),
        "hr.to_approve": ("Demandes RH à valider", "HR requests to approve")}
    active = client.get(f"{BASE}/employees", params={"f_active": "1"}).json()["total"]
    assert figures["hr.headcount"]["value"] == active > 0 and figures["hr.headcount"]["path"] == "/rh/salaries?f_active=1"

    employee = _new_employee(client)
    assert kpis()["hr.headcount"]["value"] == active + 1
    absent = figures["hr.absent_today"]["value"]
    _approved(client, employee["id"], today() - timedelta(days=3), today() + timedelta(days=3))
    assert kpis()["hr.absent_today"]["value"] == absent + 1
    assert figures["hr.absent_today"]["path"] == "/rh/absences?f_status=approved"

    pending = (db.fetch_one("SELECT COUNT(*) AS n FROM hr_absences WHERE status = 'requested'")["n"]
               + db.fetch_one("SELECT COUNT(*) AS n FROM hr_expenses WHERE status = 'submitted'")["n"])
    to_approve = kpis()["hr.to_approve"]
    assert to_approve["value"] == pending > 0 and to_approve["alert"] is True
    assert to_approve["path"] == "/rh/absences?f_status=requested"
    for row in client.get(f"{BASE}/absences", params={"f_status": "requested"}).json()["rows"]:
        client.post(f"{BASE}/absences/{row['id']}/actions/refuse")
    for row in client.get(f"{BASE}/expenses", params={"f_status": "submitted"}).json()["rows"]:
        client.post(f"{BASE}/expenses/{row['id']}/actions/approve")
    assert kpis()["hr.to_approve"]["value"] == 0 and kpis()["hr.to_approve"]["alert"] is False

    shortcuts = {s["key"]: s for s in client.get("/api/home").json()["shortcuts"]}
    assert shortcuts["hr.new_absence"]["path"] == "/rh/absences?new=1"
    assert tuple(shortcuts["hr.new_absence"]["label"]) == ("Demande d'absence", "Absence request")
    make_member("lecture.accueil@test.local", "readonly")
    home = login_as("lecture.accueil@test.local").get("/api/home").json()
    assert "hr.to_approve" in [k["key"] for k in home["kpis"]] and "hr.new_absence" not in [s["key"] for s in home["shortcuts"]]


def test_kpis_offered_in_my_views(client):
    from caffein import dashboard

    assert {"hr.headcount", "hr.absent_today", "hr.to_approve"} <= set(dashboard.module_metrics())

    def metrics(c, text: str) -> list:
        res = c.post("/api/dashboards/compose", json={"text": text})
        assert res.status_code == 200, res.text
        return [w["params"].get("metric") for w in res.json()["view"]["widgets"]]

    for text, metric in [("montre-moi les demandes RH à valider", "hr.to_approve"), ("Quel est notre effectif salarié ?", "hr.headcount"),
                         ("les salariés absents aujourd'hui", "hr.absent_today"), ("Employee headcount", "hr.headcount")]:
        assert metrics(client, text) == [metric], text
    home = {k["key"]: k for k in client.get("/api/home").json()["kpis"]}
    view = client.post("/api/dashboards/render", json={"spec": {"widgets": [{"source": "kpi", "params": {"metric": "hr.to_approve"}}]}})
    data = view.json()["widgets"][0]["data"]
    assert data["value"] == home["hr.to_approve"]["value"] > 0 and data["alert"] is True
    # une demande sans rapport avec les RH ne prend pas leurs chiffres clés
    for text in ("mes factures à valider", "les commandes en cours ce mois", "les absences de paiement", "mes salaires"):
        assert not [m for m in metrics(client, text) if str(m).startswith("hr.")], text
    # sans accès aux RH, pas de carte RH
    make_member("vues.rh@test.local", "team", {"hr": 0})
    assert metrics(login_as("vues.rh@test.local"), "montre-moi les demandes RH à valider") == []


def test_meta_and_disabled_module(client, restore_modules):
    meta = client.get("/api/meta").json()
    module = next(m for m in meta["modules"] if m["key"] == "hr")
    assert module["slug"] == "rh" and [p["slug"] for p in module["pages"]] == ["salaries", "absences", "notes-de-frais", "services"]
    entities = meta["entities"]
    assert {"hr.employees", "hr.absences", "hr.expenses", "hr.departments"} <= set(entities)
    assert entities["hr.employees"]["title"] == "full_name"
    assert [a["key"] for a in entities["hr.absences"]["actions"]] == ["approve", "refuse", "cancel"]
    assert {a["key"]: a["level"] for a in entities["hr.expenses"]["actions"]} == {"submit": 2, "approve": 3, "refuse": 3, "pay": 3}
    assert entities["hr.expenses"]["children"][0]["key"] == "lines"
    computed = {f["name"] for f in entities["hr.employees"]["fields"] if f["computed"]}
    assert computed == {"seniority_years", "leave_taken", "leave_balance"}

    disable_module(client, "hr")
    assert client.get(f"{BASE}/employees").status_code == 404
    assert client.post(f"{BASE}/absences", json={}).status_code == 404
    assert "hr" not in [m["key"] for m in client.get("/api/meta").json()["modules"]]
    home = client.get("/api/home").json()
    assert not [k for k in home["kpis"] if k["module"] == "hr"] and not [s for s in home["shortcuts"] if s["module"] == "hr"]


def test_demo_team(demo):
    rows = db.fetch_all("SELECT e.*, d.name AS department FROM hr_employees e LEFT JOIN hr_departments d ON d.id = e.department_id")
    team = {r["full_name"]: r for r in rows}
    expected = {
        "Alex Durand": ("Direction", "Gérant", "cdi"), "Camille Roux": ("Création", "Graphiste", "cdi"),
        "Hugo Martin": ("Atelier", "Opérateur d'impression", "cdi"),
        "Léa Bernard": ("Administration", "Assistante de gestion", "cdd"),
        "Nina Lefèvre": ("Création", "Stagiaire graphiste", "intern"),
    }
    for name, (department, job, contract) in expected.items():
        employee = team[name]
        assert (employee["department"], employee["job_title"], employee["contract_type"]) == (department, job, contract)
        assert employee["salary"] > 0 and employee["hire_date"] <= today().isoformat() and employee["code"].startswith("MAT-")
    managers = {r["name"]: r["manager"] for r in db.fetch_all(
        "SELECT d.name, e.full_name AS manager FROM hr_departments d LEFT JOIN hr_employees e ON e.id = d.manager_id")}
    assert managers == {"Direction": "Alex Durand", "Création": "Camille Roux", "Atelier": "Hugo Martin",
                        "Administration": "Alex Durand"}

    absences = {r["full_name"]: r for r in db.fetch_all(
        "SELECT e.full_name, a.* FROM hr_absences a JOIN hr_employees e ON e.id = a.employee_id")}
    next_monday = today() + timedelta(days=7 - today().weekday())
    camille, hugo, lea = absences["Camille Roux"], absences["Hugo Martin"], absences["Léa Bernard"]
    assert (camille["kind"], camille["status"], camille["start_date"]) == ("paid_leave", "approved", next_monday.isoformat())
    assert (hugo["kind"], hugo["status"]) == ("sick", "approved") and hugo["end_date"] < (next_monday - timedelta(days=7)).isoformat()
    assert (lea["kind"], lea["status"]) == ("rtt", "requested") and lea["start_date"] >= (today() + timedelta(days=10)).isoformat()

    reports = {r["full_name"]: r for r in db.fetch_all(
        "SELECT e.full_name, x.* FROM hr_expenses x JOIN hr_employees e ON e.id = x.employee_id")}
    assert reports["Camille Roux"]["status"] == "submitted" and reports["Hugo Martin"]["status"] == "draft"
    assert reports["Alex Durand"]["status"] == "paid" and reports["Alex Durand"]["paid_on"]
    assert not [d for d in services.list_documents() if d["source"] == "expense"]   # aucun justificatif de démonstration


def test_services_for_other_modules(client):
    camille = _employee_id("Camille Roux")
    assert hr.employee(camille)["full_name"] == "Camille Roux" and hr.employee(None) is None
    employee = _new_employee(client)
    _approved(client, employee["id"], today() - timedelta(days=3), today() + timedelta(days=3))
    assert hr.is_absent(employee["id"]) and employee["id"] in hr.absent_employee_ids(today().isoformat())
    assert not hr.is_absent(employee["id"], today() + timedelta(days=30))
    assert hr.working_days("2026-05-11", "2026-05-15") == 4
