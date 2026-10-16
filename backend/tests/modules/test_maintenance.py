# SPDX-License-Identifier: AGPL-3.0-or-later
"""Maintenance : équipements (numérotation, contrôles, prochaine maintenance et échéance calculées, planification de la
maintenance préventive, réforme), interventions (cycle de vie, statut de l'équipement, retard, verrouillage,
suppression), droits, modules Données techniques, RH et Achats désactivés, chiffres clés, « Mes vues », vue en colonnes,
export et données de démonstration."""

import csv
import io
from datetime import date, timedelta

import pytest

from caffein import dashboard, db
from caffein.core import modules as registry
from caffein.core.errors import Conflict
from caffein.modules.maintenance.entities import EQUIPMENT, due_status, next_maintenance
from caffein.utils import fmt_date, fmt_number, today

from .helpers import disable_module, login_as, make_member

BASE = "/api/data/maintenance"
NOT_NOW = "Cette action n'est pas possible dans l'état actuel de la fiche."
DONE = "Intervention terminée : elle ne se modifie plus."
CANCELLED = "Intervention annulée : elle ne se modifie plus."
ONLY_PLANNED = "Seule une intervention planifiée ou annulée peut être supprimée."
COMPUTED = ("last_maintenance", "next_maintenance", "due_status", "planned_maintenance", "open_interventions")


@pytest.fixture()
def restore_modules():
    yield
    registry.enable_all()


def _day(offset: int = 0) -> str:
    return (today() + timedelta(days=offset)).isoformat()


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


def _equipment(client, name: str = "Relieuse", **extra) -> dict:
    return _post(client, "equipment", {"name": name, **extra})


def _job(client, equipment: dict, title: str = "Réglage", **extra) -> dict:
    return _post(client, "interventions", {"equipment_id": equipment["id"], "title": title, **extra})


def _act(client, entity: str, row: dict, action: str, payload: dict | None = None):
    return client.post(f"{BASE}/{entity}/{row['id']}/actions/{action}", json=payload or {})


def _figures(row: dict) -> dict:
    return {k: row[k] for k in COMPUTED}


def _status(client, equipment: dict) -> str:
    return _get(client, "equipment", equipment)["status"]


def _workcenter(name: str) -> int:
    return db.fetch_one("SELECT id FROM technical_workcenters WHERE name = ?", (name,))["id"]


def _employee(name: str) -> int:
    return db.fetch_one("SELECT id FROM hr_employees WHERE full_name = ?", (name,))["id"]


# ═════════════════════════════════════════════════════════════════════════
# Déclaration
# ═════════════════════════════════════════════════════════════════════════
def test_meta_describes_the_module(client):
    meta = client.get("/api/meta").json()
    module = next(m for m in meta["modules"] if m["key"] == "maintenance")
    assert module["slug"] == "maintenance" and module["label"] == ["Maintenance", "Maintenance"]
    assert module["icon"] == "Wrench" and registry.get("maintenance").depends == () and registry.get("maintenance").order == 85
    assert [(p["slug"], p["entity"]) for p in module["pages"]] == [("interventions", "maintenance.interventions"),
                                                                   ("equipements", "maintenance.equipment")]
    equipment = meta["entities"]["maintenance.equipment"]
    assert equipment["label"] == ["Équipement", "Equipment"] and equipment["plural"] == ["Équipements", "Equipment"]
    assert equipment["title"] == "name" and equipment["board"] == "status"
    assert [(a["key"], a["level"], a["label"][0]) for a in equipment["actions"]] == [
        ("schedule", 2, "Planifier la maintenance")]
    fields = {f["name"]: f for f in equipment["fields"]}
    assert fields["code"]["prefix"] == "EQ" and fields["code"]["readonly"] and fields["name"]["required"]
    assert fields["workcenter_id"]["ref"] == "technical.workcenters" and fields["workcenter_id"]["filter"]
    assert fields["supplier_id"]["ref"] == "purchases.suppliers" and fields["serial_number"]["search"]
    assert (fields["interval_days"]["min"], fields["interval_days"]["max"], fields["interval_days"]["type"]) == (0, 3650, "int")
    assert fields["interval_days"]["label"] == ["Périodicité de maintenance (jours)", "Maintenance interval (days)"]
    assert [(c["value"], c["label"][0], c["tone"]) for c in fields["status"]["choices"]] == [
        ("operational", "En service", "good"), ("degraded", "Dégradé", "warn"), ("down", "En panne", "bad"),
        ("retired", "Réformé", "outline")]
    assert not fields["status"]["readonly"] and fields["status"]["default"] == "operational" and fields["status"]["filter"]
    assert all(fields[name]["computed"] for name in COMPUTED)
    assert [(c["value"], c["label"][0], c["tone"]) for c in fields["due_status"]["choices"]] == [
        ("ok", "À jour", "good"), ("soon", "Bientôt", "warn"), ("overdue", "En retard", "bad")]
    assert [name for name, f in fields.items() if f["list"]] == ["code", "name", "workcenter_id", "status",
                                                                 "next_maintenance", "due_status"]
    jobs = meta["entities"]["maintenance.interventions"]
    assert jobs["label"] == ["Intervention", "Maintenance job"] and jobs["title"] == "title" and jobs["board"] == "status"
    assert [(a["key"], a["level"]) for a in jobs["actions"]] == [("start", 2), ("done", 2), ("cancel", 2)]
    assert [a["key"] for a in jobs["actions"] if a["confirm"]] == ["cancel"]
    job_fields = {f["name"]: f for f in jobs["fields"]}
    assert job_fields["code"]["prefix"] == "INT" and job_fields["equipment_id"]["ref"] == "maintenance.equipment"
    assert job_fields["equipment_id"]["required"] and job_fields["equipment_id"]["filter"]
    assert [(c["value"], c.get("tone")) for c in job_fields["kind"]["choices"]] == [("preventive", "info"),
                                                                                    ("corrective", "warn")]
    assert [(c["value"], c["label"][0], c.get("tone")) for c in job_fields["status"]["choices"]] == [
        ("planned", "Planifiée", None), ("in_progress", "En cours", "info"), ("done", "Terminée", "good"),
        ("cancelled", "Annulée", "outline")]
    assert job_fields["status"]["readonly"] and job_fields["done_on"]["readonly"] and job_fields["overdue"]["computed"]
    assert job_fields["planned_date"]["default"] == _day() and job_fields["technician_id"]["ref"] == "hr.employees"
    assert [name for name, f in job_fields.items() if f["list"]] == ["code", "equipment_id", "kind", "title",
                                                                     "planned_date", "done_on", "status", "overdue", "cost"]


# ═════════════════════════════════════════════════════════════════════════
# Équipements : numérotation, contrôles, calculs
# ═════════════════════════════════════════════════════════════════════════
def test_equipment_numbering_and_validation(client):
    count = db.fetch_one("SELECT COUNT(*) AS n FROM maintenance_equipment")["n"]
    press = _equipment(client, "Presse à dorer", code="PIRATE", serial_number="PD-77-1203", next_maintenance=_day())
    assert press["code"] == f"EQ-{count + 1:04d}" and press["status"] == "operational"
    assert _figures(press) == {"last_maintenance": None, "next_maintenance": None, "due_status": None,
                               "planned_maintenance": None, "open_interventions": 0}
    assert press["_actions"] == [] and press["_locked"] is None and press["_deletable"] is True  # pas de périodicité
    assert _equipment(client, "Rogneuse")["code"] == f"EQ-{count + 2:04d}"
    label = "Périodicité de maintenance (jours)"
    cases = (
        ({}, "Nom : obligatoire."),
        ({"name": "X" * 121}, "Nom : 120 caractères au plus."),
        ({"name": "X", "interval_days": -1}, f"{label} : 0 au minimum."),
        ({"name": "X", "interval_days": 3651}, f"{label} : {fmt_number(3650)} au maximum."),
        ({"name": "X", "interval_days": 1.5}, f"{label} : nombre entier attendu."),
        ({"name": "X", "status": "broken"}, "Statut : valeur non proposée."),
        ({"name": "X", "status": ""}, "Statut : obligatoire."),
        ({"name": "X", "purchase_date": _day(1)}, "Date d'achat : la date ne peut pas être dans le futur."),
        ({"name": "X", "purchase_date": "2026-13-01"}, "Date d'achat : date invalide."),
        ({"name": "X", "workcenter_id": 999999}, "Poste de charge : fiche introuvable."),
        ({"name": "X", "supplier_id": 999999}, "Fournisseur : fiche introuvable."),
    )
    for data, message in cases:
        assert _error(client.post(f"{BASE}/equipment", json=data)) == message, data
    # références, recherche, filtres, choix dans un formulaire
    cutter = _workcenter("Massicot")
    linked = _equipment(client, "Massicot de secours", workcenter_id=cutter, serial_number="MS-2048")
    assert linked["workcenter_id__label"] == "Massicot"
    assert [r["id"] for r in client.get(f"{BASE}/equipment", params={"q": "MS-2048"}).json()["rows"]] == [linked["id"]]
    rows = client.get(f"{BASE}/equipment", params={"f_workcenter_id": cutter, "size": 200}).json()["rows"]
    assert linked["id"] in [r["id"] for r in rows] and {r["workcenter_id"] for r in rows} == {cutter}
    options = client.get(f"{BASE}/equipment/options", params={"q": "secours"}).json()
    assert options == [{"id": linked["id"], "label": "Massicot de secours", "sublabel": linked["code"]}]


def test_next_maintenance_rule_on_fixed_dates():
    day = date(2026, 3, 10)
    assert next_maintenance("2026-01-10", "2020-01-01", 90) == date(2026, 4, 10)  # la dernière maintenance d'abord
    assert next_maintenance(None, "2025-03-10", 365) == date(2026, 3, 10)        # à défaut, la date d'achat
    assert next_maintenance(None, None, 90) is None                               # pas de date de départ
    assert next_maintenance("2026-01-10", None, None) is None and next_maintenance("2026-01-10", None, 0) is None
    assert next_maintenance("2026-01-10", None, 90, "retired") is None            # réformé : plus de maintenance
    assert next_maintenance(None, "9999-12-30", 3650) is None                     # hors calendrier : rien plutôt qu'une erreur
    assert [due_status(day + timedelta(days=n), day) for n in (-1, 0, 7, 8)] == ["overdue", "soon", "soon", "ok"]
    assert due_status(None, day) is None


def test_next_maintenance_and_due_status(client):
    eq = _equipment(client, interval_days=30, purchase_date=_day(-40))
    assert _figures(eq) == {"last_maintenance": None, "next_maintenance": _day(-10), "due_status": "overdue",
                            "planned_maintenance": None, "open_interventions": 0}
    assert eq["_actions"] == ["schedule"]
    # une maintenance préventive terminée relance la périodicité ; une réparation ou une annulation ne compte pas
    preventive = _job(client, eq, "Graissage", kind="preventive", planned_date=_day(-6))
    assert _get(client, "equipment", eq)["planned_maintenance"] == _day(-6)
    _act(client, "interventions", preventive, "done", {"date": _day(-5)})
    repair = _job(client, eq, "Courroie", kind="corrective")
    _act(client, "interventions", repair, "done")
    skipped = _job(client, eq, "Contrôle annulé", kind="preventive")
    _act(client, "interventions", skipped, "cancel")
    row = _get(client, "equipment", eq)
    assert _figures(row) == {"last_maintenance": _day(-5), "next_maintenance": _day(25), "due_status": "ok",
                             "planned_maintenance": None, "open_interventions": 0}
    listed = next(r for r in client.get(f"{BASE}/equipment", params={"size": 200}).json()["rows"] if r["id"] == eq["id"])
    assert _figures(listed) == _figures(row)  # la liste calcule les mêmes valeurs, par une requête groupée

    # « Bientôt » : dans les 7 jours, aujourd'hui compris ; au-delà, à jour ; la veille, en retard
    states = {}
    for offset in (-1, 0, 7, 8):
        other = _equipment(client, f"Échéance {offset}", interval_days=10, purchase_date=_day(offset - 10))
        states[offset] = (other["next_maintenance"], other["due_status"])
    assert states == {-1: (_day(-1), "overdue"), 0: (_day(), "soon"), 7: (_day(7), "soon"), 8: (_day(8), "ok")}

    # périodicité modifiée, retirée ; équipement réformé
    assert client.put(f"{BASE}/equipment/{eq['id']}", json={"interval_days": 3}).json()["next_maintenance"] == _day(-2)
    for value in (0, None):
        row = client.put(f"{BASE}/equipment/{eq['id']}", json={"interval_days": value}).json()
        assert (row["next_maintenance"], row["due_status"], row["_actions"]) == (None, None, [])
    retired = client.put(f"{BASE}/equipment/{eq['id']}", json={"interval_days": 30, "status": "retired"}).json()
    assert (retired["last_maintenance"], retired["next_maintenance"], retired["due_status"]) == (_day(-5), None, None)
    assert retired["_actions"] == []

    # aperçu pendant la saisie : le serveur recalcule avec les valeurs saisies, sans rien enregistrer
    fresh = _equipment(client, "Plieuse", interval_days=90)
    preview = client.post(f"{BASE}/equipment/preview", params={"id": fresh["id"]},
                          json={"interval_days": 10, "purchase_date": _day(-3)}).json()["computed"]
    assert preview == {"last_maintenance": None, "next_maintenance": _day(7), "due_status": "soon",
                       "planned_maintenance": None, "open_interventions": 0}
    assert _get(client, "equipment", fresh)["next_maintenance"] is None  # sans date de départ
    empty = client.post(f"{BASE}/equipment/preview", json={}).json()["computed"]
    assert empty == {"last_maintenance": None, "next_maintenance": None, "due_status": None, "planned_maintenance": None,
                     "open_interventions": 0}


# ═════════════════════════════════════════════════════════════════════════
# Planifier la maintenance
# ═════════════════════════════════════════════════════════════════════════
def test_schedule_preventive_maintenance(client):
    eq = _equipment(client, "Encarteuse", interval_days=30, purchase_date=_day(-20))
    assert eq["next_maintenance"] == _day(10) and eq["_actions"] == ["schedule"]
    res = _act(client, "equipment", eq, "schedule")
    assert res.status_code == 200, res.text
    [job] = client.get(f"{BASE}/interventions", params={"f_equipment_id": eq["id"]}).json()["rows"]
    assert res.json()["message"] == f"Maintenance préventive {job['code']} planifiée le {fmt_date(_day(10))}."
    assert (job["kind"], job["status"], job["planned_date"], job["title"]) == (
        "preventive", "planned", _day(10), "Maintenance préventive : Encarteuse")
    row = res.json()["row"]
    assert (row["planned_maintenance"], row["open_interventions"], row["_actions"]) == (_day(10), 1, [])
    assert _error(_act(client, "equipment", eq, "schedule"), 409) == NOT_NOW
    # la maintenance faite, la suivante se calcule depuis sa date et se planifie de nouveau
    _act(client, "interventions", job, "done")
    row = _get(client, "equipment", eq)
    assert (row["last_maintenance"], row["next_maintenance"], row["_actions"]) == (_day(), _day(30), ["schedule"])

    # maintenance dépassée, ou sans date de départ : planifiée aujourd'hui
    late = _equipment(client, "Assembleuse", interval_days=30, purchase_date=_day(-45))
    unknown = _equipment(client, "Agrafeuse électrique", interval_days=60)
    for equipment in (late, unknown):
        assert _act(client, "equipment", equipment, "schedule").status_code == 200
        [planned] = client.get(f"{BASE}/interventions", params={"f_equipment_id": equipment["id"]}).json()["rows"]
        assert planned["planned_date"] == _day()
    # pas de périodicité, ou équipement réformé : rien à planifier
    plain = _equipment(client, "Table lumineuse")
    gone = _equipment(client, "Ancienne plastifieuse", interval_days=30, purchase_date=_day(-10), status="retired")
    for equipment in (plain, gone):
        assert _get(client, "equipment", equipment)["_actions"] == []
        assert _error(_act(client, "equipment", equipment, "schedule"), 409) == NOT_NOW
    # une maintenance préventive en cours compte aussi : pas de seconde planification
    started = _equipment(client, "Perforeuse", interval_days=15, purchase_date=_day(-15))
    manual = _job(client, started, "Révision", kind="preventive", planned_date=_day(-1))
    _act(client, "interventions", manual, "start")
    assert _get(client, "equipment", started)["_actions"] == []


def test_simultaneous_scheduling_keeps_one_maintenance(client):
    """Deux clics sur « Planifier la maintenance » (deux personnes) : une seule intervention est créée."""
    eq = _equipment(client, "Pelliculeuse", interval_days=30, purchase_date=_day(-1))
    stale = _get(client, "equipment", eq)
    schedule = next(a for a in EQUIPMENT.actions if a.key == "schedule")
    schedule.run(stale, {}, {})
    with pytest.raises(Conflict):
        schedule.run(stale, {}, {})
    assert client.get(f"{BASE}/interventions", params={"f_equipment_id": eq["id"]}).json()["total"] == 1


# ═════════════════════════════════════════════════════════════════════════
# Interventions : cycle de vie et statut de l'équipement
# ═════════════════════════════════════════════════════════════════════════
def test_repair_marks_the_equipment_down_then_back_in_service(client):
    eq = _equipment(client, "Massicot d'appoint")
    job = _job(client, eq, "Lame émoussée", technician_id=_employee("Hugo Martin"))
    assert (job["kind"], job["status"], job["planned_date"], job["done_on"]) == ("corrective", "planned", _day(), None)
    assert job["code"].startswith(f"INT-{today().year}-") and job["technician_id__label"] == "Hugo Martin"
    assert job["_actions"] == ["start", "done", "cancel"] and job["_deletable"] is True
    res = _act(client, "interventions", job, "start")
    assert res.json()["message"] == f"Intervention {job['code']} démarrée. L'équipement passe « En panne »."
    assert res.json()["row"]["status"] == "in_progress" and res.json()["row"]["_actions"] == ["done", "cancel"]
    assert res.json()["row"]["_deletable"] is False and _status(client, eq) == "down"
    assert _error(_act(client, "interventions", job, "start"), 409) == NOT_NOW
    # en cours : le compte rendu se complète, mais l'équipement et le type ne changent plus
    url = f"{BASE}/interventions/{job['id']}"
    other = _equipment(client, "Autre machine")
    assert _error(client.put(url, json={"equipment_id": other["id"]})) == \
        "Équipement : l'intervention a commencé, il ne change plus."
    assert _error(client.put(url, json={"kind": "preventive"})) == "Type : l'intervention a commencé, il ne change plus."
    assert _error(client.delete(url), 409) == ONLY_PLANNED
    updated = client.put(url, json={"report": "Lame affûtée.", "duration_hours": "1,5", "cost": 85}).json()
    assert (updated["report"], updated["duration_hours"], updated["cost"]) == ("Lame affûtée.", 1.5, 85)

    for value, message in ((_day(1), "Terminée le : la date ne peut pas être dans le futur."),
                           ("hier", "Terminée le : date invalide.")):
        assert _error(_act(client, "interventions", job, "done", {"date": value})) == message
    res = _act(client, "interventions", job, "done")
    assert res.json()["message"] == f"Intervention {job['code']} terminée. L'équipement est de nouveau « En service »."
    row = res.json()["row"]
    assert (row["status"], row["done_on"], row["_locked"], row["_actions"], row["_deletable"]) == (
        "done", _day(), DONE, [], False)
    assert _status(client, eq) == "operational"
    for action in ("start", "done", "cancel"):
        assert _error(_act(client, "interventions", job, action), 409) == NOT_NOW
    assert _error(client.put(url, json={"report": "x"}), 409) == DONE
    assert _error(client.delete(url), 409) == ONLY_PLANNED


def test_equipment_status_follows_the_interventions(client):
    eq = _equipment(client, "Imprimante grand format", status="degraded")
    # une maintenance préventive démarrée ne met pas l'équipement en panne ; terminée, elle le remet en service
    check = _job(client, eq, "Nettoyage des têtes", kind="preventive")
    assert _act(client, "interventions", check, "start").json()["message"] == f"Intervention {check['code']} démarrée."
    assert _status(client, eq) == "degraded"
    _act(client, "interventions", check, "done")
    assert _status(client, eq) == "operational"
    # terminer sur un équipement déjà en service : rien à signaler ; terminer directement une intervention planifiée
    quick = _job(client, eq, "Réglage rapide", kind="preventive")
    assert _act(client, "interventions", quick, "done").json()["message"] == f"Intervention {quick['code']} terminée."

    # deux réparations en cours : l'équipement reste en panne jusqu'à la fin de la dernière
    first, second = _job(client, eq, "Moteur"), _job(client, eq, "Capteur")
    _act(client, "interventions", first, "start")
    assert _act(client, "interventions", second, "start").json()["message"] == f"Intervention {second['code']} démarrée."
    _act(client, "interventions", first, "done")
    assert _status(client, eq) == "down"
    _act(client, "interventions", second, "done")
    assert _status(client, eq) == "operational"

    # annuler une réparation en cours : l'équipement reste en panne, l'utilisateur le remet en service lui-même
    broken = _job(client, eq, "Carte électronique")
    _act(client, "interventions", broken, "start")
    res = _act(client, "interventions", broken, "cancel")
    assert res.json()["message"] == (f"Intervention {broken['code']} annulée. L'équipement reste « En panne » : modifiez "
                                     "son statut dans sa fiche s'il fonctionne.")
    row = res.json()["row"]
    assert (row["status"], row["_locked"], row["_deletable"]) == ("cancelled", CANCELLED, True)
    assert _status(client, eq) == "down"
    assert client.put(f"{BASE}/equipment/{eq['id']}", json={"status": "operational"}).json()["status"] == "operational"
    planned = _job(client, eq, "Révision annulée")
    assert _act(client, "interventions", planned, "cancel").json()["message"] == f"Intervention {planned['code']} annulée."
    assert _error(_act(client, "interventions", planned, "start"), 409) == NOT_NOW

    # un équipement réformé ne change plus de statut (intervention ouverte avant la réforme)
    legacy = _job(client, eq, "Dernière réparation")
    db.execute("UPDATE maintenance_equipment SET status = 'retired' WHERE id = ?", (eq["id"],))
    _act(client, "interventions", legacy, "start")
    _act(client, "interventions", legacy, "done", {"date": _day(-1)})
    assert _status(client, eq) == "retired" and _get(client, "interventions", legacy)["done_on"] == _day(-1)


def test_intervention_validation_and_overdue_flag(client):
    eq = _equipment(client, "Thermorelieuse")
    cases = (
        ({}, "Équipement : obligatoire."),
        ({"equipment_id": eq["id"]}, "Intitulé : obligatoire."),
        ({"equipment_id": 999999, "title": "X"}, "Équipement : fiche introuvable."),
        ({"equipment_id": eq["id"], "title": "X", "kind": "repair"}, "Type : valeur non proposée."),
        ({"equipment_id": eq["id"], "title": "X", "planned_date": None}, "Date prévue : obligatoire."),
        ({"equipment_id": eq["id"], "title": "X", "duration_hours": -1}, "Durée (heures) : 0 au minimum."),
        ({"equipment_id": eq["id"], "title": "X", "cost": -5}, "Coût : 0 au minimum."),
        ({"equipment_id": eq["id"], "title": "X", "technician_id": 999999}, "Technicien : fiche introuvable."),
    )
    for data, message in cases:
        assert _error(client.post(f"{BASE}/interventions", json=data)) == message, data
    # le statut et la date de fin ne se posent que par les boutons
    job = _job(client, eq, "Réglage de la température", status="done", done_on=_day(), planned_date=_day(-1))
    assert (job["status"], job["done_on"], job["overdue"]) == ("planned", None, True)
    assert _job(client, eq, "Contrôle du jour")["overdue"] is False
    started = _act(client, "interventions", job, "start").json()["row"]
    assert started["overdue"] is False  # en cours : plus en retard
    listed = {r["id"]: r for r in client.get(f"{BASE}/interventions", params={"f_equipment_id": eq["id"]}).json()["rows"]}
    assert listed[job["id"]]["overdue"] is False
    # planifiée : elle change d'équipement librement ; un équipement réformé ne reçoit plus d'intervention
    spare = _job(client, eq, "Graissage")
    other = _equipment(client, "Thermorelieuse 2")
    assert client.put(f"{BASE}/interventions/{spare['id']}", json={"equipment_id": other["id"]}).json()["equipment_id"] == other["id"]
    gone = _equipment(client, "Ancienne relieuse", status="retired")
    retired = "Équipement : il est réformé, on n'y prévoit plus d'intervention."
    assert _error(client.post(f"{BASE}/interventions", json={"equipment_id": gone["id"], "title": "X"})) == retired
    assert _error(client.put(f"{BASE}/interventions/{spare['id']}", json={"equipment_id": gone["id"]})) == retired


# ═════════════════════════════════════════════════════════════════════════
# Suppression et réforme
# ═════════════════════════════════════════════════════════════════════════
def test_deletion_and_retirement_rules(client):
    center = client.post("/api/data/technical/workcenters", json={"name": "Poste de reliure"}).json()
    eq = _equipment(client, "Relieuse à spirales", workcenter_id=center["id"], interval_days=30)
    planned, started, finished = _job(client, eq, "A"), _job(client, eq, "B"), _job(client, eq, "C")
    _act(client, "interventions", started, "start")
    _act(client, "interventions", finished, "done")
    assert _error(client.delete(f"{BASE}/equipment/{eq['id']}"), 409) == \
        "Suppression impossible : cette fiche est utilisée ailleurs (interventions : 3)."
    assert "équipements : 1" in _error(client.delete(f"/api/data/technical/workcenters/{center['id']}"), 409)
    # réformer : seulement sans intervention ouverte
    retire = "Statut : terminez ou annulez d'abord les interventions ouvertes de cet équipement avant de le réformer."
    assert _error(client.put(f"{BASE}/equipment/{eq['id']}", json={"status": "retired"})) == retire
    assert client.delete(f"{BASE}/interventions/{planned['id']}").status_code == 204
    assert _error(client.put(f"{BASE}/equipment/{eq['id']}", json={"status": "retired"})) == retire
    _act(client, "interventions", started, "cancel")
    assert client.delete(f"{BASE}/interventions/{started['id']}").status_code == 204
    row = client.put(f"{BASE}/equipment/{eq['id']}", json={"status": "retired"}).json()
    assert (row["status"], row["open_interventions"], row["next_maintenance"], row["_actions"]) == ("retired", 0, None, [])
    # l'intervention terminée reste dans l'historique et retient l'équipement
    assert _error(client.delete(f"{BASE}/interventions/{finished['id']}"), 409) == ONLY_PLANNED
    assert _error(client.delete(f"{BASE}/equipment/{eq['id']}"), 409) == \
        "Suppression impossible : cette fiche est utilisée ailleurs (interventions : 1)."
    spare = _equipment(client, "Machine jamais utilisée")
    assert client.delete(f"{BASE}/equipment/{spare['id']}").status_code == 204


# ═════════════════════════════════════════════════════════════════════════
# Droits
# ═════════════════════════════════════════════════════════════════════════
def test_readonly_role_cannot_write(client):
    eq = _equipment(client, interval_days=30, purchase_date=_day(-1))
    job = _job(client, eq)
    make_member("lecture-maintenance@test.local", "readonly")
    reader = login_as("lecture-maintenance@test.local")
    assert reader.get(f"{BASE}/equipment").status_code == 200 and reader.get(f"{BASE}/interventions").status_code == 200
    assert reader.get(f"{BASE}/equipment/{eq['id']}").json()["_actions"] == []
    assert reader.post(f"{BASE}/equipment", json={"name": "Lecture"}).status_code == 403
    assert reader.put(f"{BASE}/equipment/{eq['id']}", json={"name": "x"}).status_code == 403
    assert reader.delete(f"{BASE}/equipment/{eq['id']}").status_code == 403
    assert reader.post(f"{BASE}/equipment/{eq['id']}/actions/schedule").status_code == 403
    assert reader.post(f"{BASE}/interventions", json={"equipment_id": eq["id"], "title": "x"}).status_code == 403
    assert reader.put(f"{BASE}/interventions/{job['id']}", json={"title": "x"}).status_code == 403
    assert reader.post(f"{BASE}/interventions/preview", json={}).status_code == 403
    for action in ("start", "done", "cancel"):
        assert reader.post(f"{BASE}/interventions/{job['id']}/actions/{action}").status_code == 403
    assert reader.delete(f"{BASE}/interventions/{job['id']}").status_code == 403
    home = reader.get("/api/home").json()
    assert "maintenance.equipment_down" in {k["key"] for k in home["kpis"]}
    assert "maintenance.new_intervention" not in {s["key"] for s in home["shortcuts"]}
    assert _get(client, "interventions", job)["status"] == "planned"


def test_team_member_runs_the_maintenance(client):
    make_member("atelier-maintenance@test.local", "team")  # écriture sur tous les modules
    member = login_as("atelier-maintenance@test.local")
    eq = member.post(f"{BASE}/equipment", json={"name": "Cisaille", "interval_days": 30, "purchase_date": _day(-30)})
    assert eq.status_code == 201 and eq.json()["_deletable"] is False  # suppression : gestion
    eq = eq.json()
    assert member.post(f"{BASE}/equipment/{eq['id']}/actions/schedule").status_code == 200
    [job] = member.get(f"{BASE}/interventions", params={"f_equipment_id": eq["id"]}).json()["rows"]
    assert member.post(f"{BASE}/interventions/{job['id']}/actions/start").status_code == 200
    assert member.post(f"{BASE}/interventions/{job['id']}/actions/done").status_code == 200
    assert member.delete(f"{BASE}/interventions/{job['id']}").status_code == 403
    assert member.delete(f"{BASE}/equipment/{eq['id']}").status_code == 403
    assert "maintenance.new_intervention" in {s["key"] for s in member.get("/api/home").json()["shortcuts"]}


# ═════════════════════════════════════════════════════════════════════════
# Modules désactivés
# ═════════════════════════════════════════════════════════════════════════
def test_disabled_maintenance_disappears(client, restore_modules):
    eq = _equipment(client, workcenter_id=_workcenter("Atelier de façonnage"))
    job = _job(client, eq)
    disable_module(client, "maintenance")
    assert client.get(f"{BASE}/equipment").status_code == 404
    assert client.get(f"{BASE}/interventions/{job['id']}").status_code == 404
    assert client.post(f"{BASE}/equipment", json={"name": "X"}).status_code == 404
    assert client.post(f"{BASE}/interventions/{job['id']}/actions/start").status_code == 404
    assert client.post(f"{BASE}/equipment/{eq['id']}/actions/schedule").status_code == 404
    meta = client.get("/api/meta").json()
    assert "maintenance" not in [m["key"] for m in meta["modules"]] and "maintenance.equipment" not in meta["entities"]
    home = client.get("/api/home").json()
    assert not [k for k in home["kpis"] if k["module"] == "maintenance"]
    assert not [s for s in home["shortcuts"] if s["module"] == "maintenance"]
    # ses données restent, et protègent toujours les fiches qu'elles désignent
    res = client.delete(f"/api/data/technical/workcenters/{_workcenter('Atelier de façonnage')}")
    assert res.status_code == 409 and "équipements" in res.json()["detail"]
    assert client.put("/api/settings/modules/maintenance", json={"enabled": True}).status_code == 200
    assert _get(client, "interventions", job)["code"] == job["code"]


def test_maintenance_works_without_the_other_modules(client, restore_modules):
    hugo, printer = _employee("Hugo Martin"), _workcenter("Imprimante numérique")
    eq = _equipment(client, "Traceur", workcenter_id=printer, interval_days=30, purchase_date=_day(-30))
    job = _job(client, eq, "Remplacer la courroie", technician_id=hugo)
    for key in ("technical", "hr", "purchases"):  # la Logistique et la Production, qui dépendent des Données techniques, d'abord
        disable_module(client, key)
    meta = client.get("/api/meta").json()["entities"]
    assert not {"workcenter_id", "supplier_id"} & {f["name"] for f in meta["maintenance.equipment"]["fields"]}
    assert "technician_id" not in {f["name"] for f in meta["maintenance.interventions"]["fields"]}
    row = _get(client, "equipment", eq)
    assert "workcenter_id" not in row and row["due_status"] == "soon"
    assert client.put(f"{BASE}/equipment/{eq['id']}", json={"name": "Traceur A0"}).status_code == 200
    assert _act(client, "equipment", eq, "schedule").status_code == 200
    assert _act(client, "interventions", job, "start").json()["row"]["status"] == "in_progress"
    assert _act(client, "interventions", job, "done").status_code == 200
    created = _job(client, eq, "Sans technicien", technician_id=hugo)  # champ masqué : ignoré
    assert client.get(f"{BASE}/interventions/export").status_code == 200
    assert {"maintenance.maintenance_due", "maintenance.equipment_down", "maintenance.cost_year"} <= {
        k["key"] for k in client.get("/api/home").json()["kpis"]}
    registry.enable_all()
    assert _get(client, "equipment", eq)["workcenter_id__label"] == "Imprimante numérique"
    assert _get(client, "interventions", job)["technician_id"] == hugo
    assert _get(client, "interventions", created)["technician_id"] is None


# ═════════════════════════════════════════════════════════════════════════
# Chiffres clés, « Mes vues », vue en colonnes, export
# ═════════════════════════════════════════════════════════════════════════
def _kpis(client) -> dict:
    return {k["key"]: k for k in client.get("/api/home").json()["kpis"] if k["module"] == "maintenance"}


def test_home_kpis_follow_the_equipment(client):
    start = _kpis(client)
    assert set(start) == {"maintenance.maintenance_due", "maintenance.equipment_down", "maintenance.cost_year"}
    assert start["maintenance.maintenance_due"]["path"] == "/maintenance/equipements"
    assert start["maintenance.equipment_down"]["path"] == "/maintenance/equipements?f_status=down"
    assert start["maintenance.cost_year"]["unit"] == "money" and start["maintenance.cost_year"]["path"] == "/maintenance/interventions"
    shortcut = next(s for s in client.get("/api/home").json()["shortcuts"] if s["key"] == "maintenance.new_intervention")
    assert shortcut["path"] == "/maintenance/interventions?new=1" and shortcut["label"] == ["Intervention", "Maintenance job"]

    # rien à prévoir, rien en panne : aucune alerte
    db.execute("UPDATE maintenance_equipment SET interval_days = NULL, status = 'operational'")
    calm = _kpis(client)
    assert (calm["maintenance.maintenance_due"]["value"], calm["maintenance.maintenance_due"]["alert"]) == (0, False)
    assert (calm["maintenance.equipment_down"]["value"], calm["maintenance.equipment_down"]["alert"]) == (0, False)

    _equipment(client, "Bientôt", interval_days=30, purchase_date=_day(-25))
    _equipment(client, "En retard", interval_days=30, purchase_date=_day(-40))
    _equipment(client, "À jour", interval_days=30, purchase_date=_day(-5))
    _equipment(client, "Réformé en retard", interval_days=30, purchase_date=_day(-40), status="retired")
    due = _kpis(client)["maintenance.maintenance_due"]
    assert (due["value"], due["count"], due["alert"]) == (2, 1, True)
    rows = client.get(f"{BASE}/equipment", params={"size": 200}).json()["rows"]
    assert due["value"] == len([r for r in rows if r["due_status"] in ("soon", "overdue")])

    eq = _equipment(client, "Cisaille")
    repair = _job(client, eq, "Lame cassée", cost=120.505)
    _act(client, "interventions", repair, "start")
    down = _kpis(client)["maintenance.equipment_down"]
    assert (down["value"], down["alert"]) == (1, True)
    assert down["value"] == client.get(f"{BASE}/equipment", params={"f_status": "down"}).json()["total"]
    _act(client, "interventions", repair, "done")
    _act(client, "interventions", _job(client, eq, "Révision de l'an dernier", cost=1000), "done",
         {"date": f"{today().year - 1}-12-31"})
    _job(client, eq, "Planifiée, avec un devis", cost=300)
    _act(client, "interventions", _job(client, eq, "Annulée", cost=50), "cancel")
    end = _kpis(client)
    assert end["maintenance.equipment_down"]["value"] == 0
    year = start["maintenance.cost_year"]
    assert end["maintenance.cost_year"]["value"] == round(year["value"] + 120.51, 2)  # terminées cette année seulement
    assert end["maintenance.cost_year"]["count"] == year["count"] + 1


def test_kpis_are_offered_in_my_views(client):
    def widgets(text):
        return dashboard.compose_offline(text, {})["spec"]["widgets"]

    module = registry.get("maintenance")
    assert [k.key for k in module.kpis] == ["maintenance_due", "equipment_down", "cost_year"]
    for kpi in module.kpis:
        for label in kpi.label:
            assert [(w["source"], w["params"].get("metric")) for w in widgets(f"Montre-moi : {label.lower()}")] == [
                ("kpi", f"maintenance.{kpi.key}")], label
    for text in ("mes factures en retard", "le total en retard", "mes dépenses de l'année", "les ordres de fabrication en retard"):
        assert not [w for w in widgets(text) if w["params"].get("metric", "").startswith("maintenance.")], text
    res = client.post("/api/dashboards/compose", json={"text": "Montre-moi les équipements en panne"})
    [card] = [w for w in res.json()["view"]["widgets"] if w["source"] == "kpi"]
    down = client.get(f"{BASE}/equipment", params={"f_status": "down"}).json()["total"]
    assert card["params"]["metric"] == "maintenance.equipment_down" and card["data"]["value"] == down


def test_board_counts_and_costs_by_status(client):
    before = {c["value"]: c for c in client.get(f"{BASE}/interventions/board").json()["columns"]}
    eq = _equipment(client)
    _job(client, eq, "A", cost=40)
    _job(client, eq, "B", cost="12,25")
    _act(client, "interventions", _job(client, eq, "C", cost=100), "done")
    board = client.get(f"{BASE}/interventions/board").json()
    assert board["field"] == "status" and board["amount_field"] == "cost"
    columns = {c["value"]: c for c in board["columns"]}
    assert list(columns) == ["planned", "in_progress", "done", "cancelled"]
    assert columns["planned"]["count"] == before["planned"]["count"] + 2
    assert columns["planned"]["amount"] == round(before["planned"]["amount"] + 52.25, 2)
    assert columns["done"]["amount"] == round(before["done"]["amount"] + 100, 2)
    equipment = {c["value"]: c for c in client.get(f"{BASE}/equipment/board").json()["columns"]}
    assert list(equipment) == ["operational", "degraded", "down", "retired"] and equipment["operational"]["count"] >= 1


def test_export_lists_the_computed_dates(client):
    eq = _equipment(client, "Plieuse automatique", interval_days=30, purchase_date=_day(-25), serial_number="PA-31")
    res = client.get(f"{BASE}/equipment/export", params={"q": "PA-31"})
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    header, *rows = list(csv.reader(io.StringIO(res.text.lstrip("﻿")), delimiter=";"))
    [row] = rows
    cells = dict(zip(header, row, strict=True))
    assert (cells["Code"], cells["Nom"], cells["Statut"]) == (eq["code"], "Plieuse automatique", "En service")
    assert (cells["Prochaine maintenance"], cells["Échéance de maintenance"]) == (fmt_date(_day(5)), "Bientôt")
    assert cells["Périodicité de maintenance (jours)"] == "30"


# ═════════════════════════════════════════════════════════════════════════
# Démonstration
# ═════════════════════════════════════════════════════════════════════════
def test_demo_data(client):
    rows = {r["name"]: r for r in client.get(f"{BASE}/equipment", params={"size": 200}).json()["rows"]}
    assert {"Imprimante numérique", "Massicot", "Plastifieuse"} <= set(rows)
    printer, cutter, laminator = rows["Imprimante numérique"], rows["Massicot"], rows["Plastifieuse"]
    assert printer["workcenter_id__label"] == "Imprimante numérique" and printer["interval_days"] == 90
    assert (printer["last_maintenance"], printer["next_maintenance"], printer["due_status"]) == (_day(-80), _day(10), "ok")
    assert printer["status"] == "operational" and _get(client, "equipment", printer)["_actions"] == ["schedule"]
    assert (cutter["interval_days"], cutter["status"], cutter["open_interventions"]) == (180, "degraded", 1)
    assert (laminator["interval_days"], laminator["next_maintenance"], laminator["due_status"]) == (365, _day(7), "soon")
    assert laminator["planned_maintenance"] == _day(7) and _get(client, "equipment", laminator)["_actions"] == []
    jobs = client.get(f"{BASE}/interventions", params={"size": 200}).json()["rows"]
    repair = next(j for j in jobs if j["title"] == "Lame émoussée")
    assert (repair["equipment_id__label"], repair["kind"], repair["status"]) == ("Massicot", "corrective", "in_progress")
    assert repair["technician_id__label"] == "Hugo Martin"
    [annual] = [j for j in jobs if j["equipment_id"] == laminator["id"]]
    assert (annual["kind"], annual["status"], annual["planned_date"]) == ("preventive", "planned", _day(7))
    kpis = _kpis(client)
    assert kpis["maintenance.maintenance_due"]["value"] == 1 and kpis["maintenance.maintenance_due"]["alert"] is True
    assert kpis["maintenance.equipment_down"]["value"] == 0
