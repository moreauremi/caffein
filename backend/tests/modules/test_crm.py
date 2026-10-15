# SPDX-License-Identifier: AGPL-3.0-or-later
"""CRM : prospects (statuts, conversion en client des Ventes), opportunités (probabilité par étape, montant pondéré,
gain, perte, devis), actions commerciales (faites, en retard), droits, module désactivé, Ventes désactivées, chiffres
clés et données de démonstration."""

import csv
import io
from datetime import timedelta

import pytest

from caffein import dashboard, db, services
from caffein.core import entities
from caffein.core import modules as registry
from caffein.core.errors import Conflict
from caffein.core.modules import MANAGE
from caffein.modules.crm.entities import ACTIVITIES, CHANGED, LEADS, OPPORTUNITIES, probability, weighted_amount
from caffein.utils import cents, today

from .helpers import disable_module, login_as, make_member

BASE = "/api/data/crm"
NOT_NOW = "Cette action n'est pas possible dans l'état actuel de la fiche."
CLOSE_BY_BUTTON = "Étape : utilisez « Marquer comme gagnée » ou « Marquer comme perdue » pour clore l'opportunité."
NO_LINK = "Prospect : choisissez un prospect ou un client."
STAGES = ["prospecting", "qualification", "proposal", "negotiation", "won", "lost"]


@pytest.fixture()
def restore_modules():
    yield
    registry.enable_all()


def _day(offset: int = 0) -> str:
    return (today() + timedelta(days=offset)).isoformat()


def _post(client, entity: str, data: dict) -> dict:
    res = client.post(f"{BASE}/{entity}", json=data)
    assert res.status_code == 201, res.text
    return res.json()


def _lead(client, company: str = "Fromagerie Mons", **extra) -> dict:
    return _post(client, "leads", {"company": company, **extra})


def _opportunity(client, title: str = "Plateaux de fêtes", **extra) -> dict:
    return _post(client, "opportunities", {"title": title, **extra})


def _activity(client, subject: str = "Appeler Odile Mons", **extra) -> dict:
    return _post(client, "activities", {"subject": subject, **extra})


def _get(client, entity: str, row: dict) -> dict:
    res = client.get(f"{BASE}/{entity}/{row['id']}")
    assert res.status_code == 200, res.text
    return res.json()


def _act(client, entity: str, row: dict, action: str):
    return client.post(f"{BASE}/{entity}/{row['id']}/actions/{action}", json={})


def _error(res, status: int = 400) -> str:
    assert res.status_code == status, res.text
    return res.json()["detail"]


def _client_id(name: str) -> int:
    return db.fetch_one("SELECT id FROM clients WHERE name = ?", (name,))["id"]


def _count(table: str, where: str = "1 = 1", params: tuple = ()) -> int:
    return db.fetch_one(f"SELECT COUNT(*) AS n FROM {table} WHERE {where}", params)["n"]


def _quotes() -> int:
    return _count("invoices", "kind = 'quote'")


def _run(entity, key: str, row: dict, user: dict | None = None):
    """Action appelée directement, sur une fiche peut-être périmée (double clic, appel interne)."""
    action = next(a for a in entity.actions if a.key == key)
    return action.run(row, {}, user or {})


# ═════════════════════════════════════════════════════════════════════════
# Description du module
# ═════════════════════════════════════════════════════════════════════════
def test_meta_describes_the_module(client):
    meta = client.get("/api/meta").json()
    module = next(m for m in meta["modules"] if m["key"] == "crm")
    assert module["slug"] == "crm" and module["label"] == ["CRM", "CRM"] and module["icon"] == "Handshake"
    assert [(p["slug"], p["entity"]) for p in module["pages"]] == [
        ("opportunites", "crm.opportunities"), ("prospects", "crm.leads"), ("actions", "crm.activities")]
    declared = registry.get("crm")
    assert declared.order == 45 and declared.depends == () and not declared.upgrade_enabled
    assert declared.reset_tables == ("crm_activities", "crm_opportunities", "crm_leads")

    opportunities = meta["entities"]["crm.opportunities"]
    assert opportunities["label"] == ["Opportunité", "Opportunity"] and opportunities["title"] == "title"
    assert opportunities["board"] == "stage" and opportunities["can_delete"]
    fields = {f["name"]: f for f in opportunities["fields"]}
    assert "quote_id" not in fields  # lu avec la fiche, jamais affiché
    assert fields["code"]["prefix"] == "OPP" and fields["code"]["readonly"]
    assert [c["value"] for c in fields["stage"]["choices"]] == STAGES
    assert fields["stage"]["default"] == "prospecting" and fields["stage"]["required"] and fields["stage"]["filter"]
    assert fields["probability"]["type"] == "percent" and (fields["probability"]["min"], fields["probability"]["max"]) == (0, 100)
    assert "default" not in fields["probability"]  # vide : le serveur prend celle de l'étape
    assert fields["amount"]["type"] == "money" and fields["amount"]["label"] == ["Montant HT", "Amount excl. VAT"]
    assert fields["weighted_amount"]["computed"] and fields["quote_number"]["computed"]
    assert fields["lead_id"]["ref"] == "crm.leads" and fields["lead_id"]["filter"]
    assert fields["client_id"]["ref"] == "sales.clients" and fields["client_id"]["filter"]
    assert fields["expected_close"]["label"] == ["Clôture prévue", "Expected close date"]
    assert [name for name, f in fields.items() if f["list"]] == ["code", "title", "client_id", "amount", "stage",
                                                                 "weighted_amount", "expected_close"]
    assert [a["key"] for a in opportunities["actions"]] == ["create_quote", "won", "lost"]
    assert [a["key"] for a in opportunities["actions"] if a["confirm"]] == ["won", "lost"]
    assert next(a for a in opportunities["actions"] if a["key"] == "lost")["style"] == "danger"

    leads = meta["entities"]["crm.leads"]
    assert leads["label"] == ["Prospect", "Lead"] and leads["title"] == "company" and leads["board"] == "status"
    lead_fields = {f["name"]: f for f in leads["fields"]}
    assert lead_fields["company"]["label"] == ["Entreprise", "Company"] and lead_fields["company"]["required"]
    assert lead_fields["company"]["search"] and lead_fields["contact_name"]["search"]
    assert [c["value"] for c in lead_fields["status"]["choices"]] == ["new", "contacted", "qualified", "converted", "lost"]
    assert lead_fields["status"]["readonly"] and lead_fields["status"]["default"] == "new"
    assert lead_fields["client_id"]["readonly"] and lead_fields["client_id"]["ref"] == "sales.clients"
    assert [c["value"] for c in lead_fields["source"]["choices"]] == ["website", "referral", "event", "social", "cold", "other"]
    assert lead_fields["email"]["type"] == "email" and lead_fields["phone"]["type"] == "phone"
    assert [name for name, f in lead_fields.items() if f["list"]] == ["company", "contact_name", "city", "source", "status"]
    assert [a["key"] for a in leads["actions"]] == ["contacted", "qualify", "convert", "lost"]
    assert [a["key"] for a in leads["actions"] if a["confirm"]] == ["convert", "lost"]

    activities = meta["entities"]["crm.activities"]
    assert activities["label"] == ["Action commerciale", "Sales activity"] and activities["board"] is None
    activity_fields = {f["name"]: f for f in activities["fields"]}
    assert [c["value"] for c in activity_fields["kind"]["choices"]] == ["call", "email", "meeting", "task"]
    assert activity_fields["due_date"]["default"] == _day() and activity_fields["done"]["default"] is False
    assert activity_fields["done"]["filter"] and activity_fields["kind"]["filter"]
    assert activity_fields["done_on"]["readonly"] and activity_fields["overdue"]["computed"]
    assert (activity_fields["done"]["label"], activity_fields["done_on"]["label"]) == (["Faite", "Done"], ["Faite le", "Done on"])
    assert [name for name, f in activity_fields.items() if f["list"]] == ["kind", "subject", "due_date", "done", "overdue",
                                                                          "lead_id"]
    assert [a["key"] for a in activities["actions"]] == ["done"]


def test_lock_and_deletion_rules():
    for status in ("new", "contacted", "qualified"):
        assert LEADS.locked({"status": status}) is None
        LEADS.before_delete({"status": status})
    assert LEADS.locked({"status": "lost"}) == "Prospect perdu : il ne se modifie plus."
    assert LEADS.locked({"status": "converted"}).startswith("Prospect converti en client : il ne se modifie plus.")
    LEADS.before_delete({"status": "converted"})  # données personnelles : un prospect se supprime toujours
    LEADS.before_delete({"status": "lost"})
    for stage in ("prospecting", "qualification", "proposal", "negotiation"):
        assert OPPORTUNITIES.locked({"stage": stage}) is None
        OPPORTUNITIES.before_delete({"stage": stage})
    assert OPPORTUNITIES.locked({"stage": "won"}) == "Opportunité gagnée : elle ne se modifie plus."
    assert OPPORTUNITIES.locked({"stage": "lost"}) == "Opportunité perdue : elle ne se modifie plus."
    OPPORTUNITIES.before_delete({"stage": "lost"})
    with pytest.raises(Conflict, match="Une opportunité gagnée ne se supprime pas : elle fait partie de l'historique"):
        OPPORTUNITIES.before_delete({"stage": "won"})
    assert ACTIVITIES.locked is None and ACTIVITIES.before_delete is None


def test_probability_rule_and_weighted_amount():
    """Une seule règle pour l'enregistrement, les montants pondérés et l'aperçu : la probabilité saisie, sinon celle
    de l'étape ; une étape changée sans nouvelle probabilité (le formulaire renvoie l'ancienne) prend celle de l'étape."""
    defaults = {"prospecting": 10, "qualification": 25, "proposal": 50, "negotiation": 75, "won": 100, "lost": 0}
    for stage, expected in defaults.items():
        assert probability(stage, None) == expected, stage
    assert probability(None, None) == 10  # sans étape : découverte
    stored = {"stage": "proposal", "probability": 60}
    assert probability("proposal", 60, stored) == 60      # rien ne change
    assert probability("proposal", 35, stored) == 35      # probabilité saisie
    assert probability("negotiation", 60, stored) == 75   # étape changée, ancienne probabilité renvoyée
    assert probability("negotiation", 40, stored) == 40   # étape et probabilité changées ensemble
    assert probability("negotiation", None, stored) == 75
    assert probability("qualification", 0) == 0           # zéro saisi : gardé
    # au centime, la moitié vers le haut (comme une facture), vide sans montant
    assert weighted_amount(1000.5, 25) == 250.13 and weighted_amount(0.25, 50) == 0.13
    assert weighted_amount(1234.56, 33) == 407.4 and weighted_amount(0, 75) == 0
    assert weighted_amount(None, 50) is None


# ═════════════════════════════════════════════════════════════════════════
# Prospects
# ═════════════════════════════════════════════════════════════════════════
def test_lead_entry_and_validation(client):
    nova = _client_id("Atelier Nova")
    lead = _lead(client, contact_name="Odile Mons", email="odile@fromagerie-mons.example", phone="04 65 71 80 12",
                 city="Lyon", source="event", status="converted", client_id=nova)
    assert lead["status"] == "new" and lead["client_id"] is None  # statut et client : remplis par le serveur
    assert (lead["source"], lead["city"], lead["_locked"]) == ("event", "Lyon", None)
    assert set(lead["_actions"]) == {"contacted", "qualify", "convert", "lost"} and lead["_deletable"] is True
    assert _lead(client, "Sans origine")["source"] == "other"
    edited = client.put(f"{BASE}/leads/{lead['id']}", json={"city": "Villeurbanne", "status": "lost", "client_id": nova})
    assert edited.status_code == 200, edited.text
    edited = edited.json()
    assert (edited["city"], edited["status"], edited["client_id"], edited["contact_name"]) == ("Villeurbanne", "new", None,
                                                                                             "Odile Mons")
    found = client.get(f"{BASE}/leads", params={"q": "odile"}).json()
    assert [r["id"] for r in found["rows"]] == [lead["id"]]
    by_source = client.get(f"{BASE}/leads", params={"f_source": "event", "size": 200}).json()["rows"]
    assert lead["id"] in {r["id"] for r in by_source} and {r["source"] for r in by_source} == {"event"}
    new = client.get(f"{BASE}/leads", params={"f_status": "new", "size": 200}).json()["rows"]
    assert lead["id"] in {r["id"] for r in new} and {r["status"] for r in new} == {"new"}
    assert client.get(f"{BASE}/leads", params={"f_status": "nope"}).status_code == 400
    options = client.get(f"{BASE}/leads/options", params={"q": "mons"}).json()
    assert [(o["id"], o["label"], o["sublabel"]) for o in options] == [(lead["id"], "Fromagerie Mons", "Villeurbanne")]
    for bad, message in (
        ({}, "Entreprise : obligatoire."),
        ({"company": "  "}, "Entreprise : obligatoire."),
        ({"company": "x" * 121}, "Entreprise : 120 caractères au plus."),
        ({"company": "A", "email": "odile@"}, "Email : adresse email invalide."),
        ({"company": "A", "phone": "le matin"}, "Téléphone : numéro invalide."),
        ({"company": "A", "source": "flyer"}, "Origine : valeur non proposée."),
        ({"company": "A", "source": None}, "Origine : obligatoire."),
    ):
        assert _error(client.post(f"{BASE}/leads", json=bad)) == message, bad


def test_lead_workflow(client):
    lead = _lead(client)
    contacted = _act(client, "leads", lead, "contacted").json()
    assert contacted["message"] == "Fromagerie Mons : prospect contacté."
    assert contacted["row"]["status"] == "contacted" and set(contacted["row"]["_actions"]) == {"qualify", "convert", "lost"}
    assert _error(_act(client, "leads", lead, "contacted"), 409) == NOT_NOW
    qualified = _act(client, "leads", lead, "qualify").json()
    assert qualified["message"] == "Fromagerie Mons : prospect qualifié." and qualified["row"]["status"] == "qualified"
    assert set(qualified["row"]["_actions"]) == {"convert", "lost"} and qualified["row"]["_locked"] is None
    for action in ("contacted", "qualify"):
        assert _error(_act(client, "leads", lead, action), 409) == NOT_NOW, action
    noted = client.put(f"{BASE}/leads/{lead['id']}", json={"notes": "Rappeler en janvier"})
    assert noted.status_code == 200 and noted.json()["notes"] == "Rappeler en janvier"  # encore modifiable

    lost = _act(client, "leads", lead, "lost").json()
    assert lost["message"] == "Fromagerie Mons : prospect perdu."
    row = lost["row"]
    assert row["status"] == "lost" and row["_actions"] == [] and row["_locked"] == "Prospect perdu : il ne se modifie plus."
    assert _error(client.put(f"{BASE}/leads/{lead['id']}", json={"notes": "x"}), 409) == row["_locked"]
    for action in ("contacted", "qualify", "convert", "lost"):
        assert _error(_act(client, "leads", lead, action), 409) == NOT_NOW, action
    # perdu mais supprimable (données personnelles), tant que rien ne le désigne
    assert row["_deletable"] is True
    assert client.delete(f"{BASE}/leads/{lead['id']}").status_code == 204
    assert client.get(f"{BASE}/leads/{lead['id']}").status_code == 404

    # un nouveau prospect se qualifie directement ; un prospect se perd depuis tout statut ouvert
    direct = _lead(client, "Qualifié d'emblée")
    assert _act(client, "leads", direct, "qualify").json()["row"]["status"] == "qualified"
    assert _act(client, "leads", _lead(client, "Perdu d'emblée"), "lost").json()["row"]["status"] == "lost"
    assert client.post(f"{BASE}/leads/{direct['id']}/actions/inconnue", json={}).status_code == 404
    assert client.post(f"{BASE}/leads/999999/actions/qualify", json={}).status_code == 404
    # une action calculée sur un état périmé (double clic) ne passe pas
    stale = {**direct, "status": "new"}
    with pytest.raises(Conflict, match=CHANGED):
        _run(LEADS, "contacted", stale)


def test_lead_deletion_is_blocked_while_used(client):
    lead = _lead(client)
    opportunity = _opportunity(client, lead_id=lead["id"])
    res = client.delete(f"{BASE}/leads/{lead['id']}")
    assert _error(res, 409) == "Suppression impossible : cette fiche est utilisée ailleurs (opportunités : 1)."
    call = _activity(client, lead_id=lead["id"])
    res = client.delete(f"{BASE}/leads/{lead['id']}")
    assert _error(res, 409) == ("Suppression impossible : cette fiche est utilisée ailleurs (opportunités : 1, "
                                "actions commerciales : 1).")
    assert client.delete(f"{BASE}/opportunities/{opportunity['id']}").status_code == 204
    assert client.delete(f"{BASE}/activities/{call['id']}").status_code == 204
    assert client.delete(f"{BASE}/leads/{lead['id']}").status_code == 204


# ═════════════════════════════════════════════════════════════════════════
# Conversion en client des Ventes
# ═════════════════════════════════════════════════════════════════════════
def test_conversion_creates_the_client_once(client):
    before = _count("clients")
    nova = _client_id("Atelier Nova")
    lead = _lead(client, contact_name="Odile Mons", email="odile@fromagerie-mons.example", phone="04 65 71 80 12",
                 city="Lyon", notes="Plateaux de fromages pour les entreprises.")
    _act(client, "leads", lead, "qualify")
    with_client = _opportunity(client, "Coffrets de Noël", lead_id=lead["id"], client_id=nova)
    without = _opportunity(client, "Étiquettes de fromages", lead_id=lead["id"], amount=900)
    other = _opportunity(client, "Autre prospect", lead_id=_lead(client, "Autre prospect")["id"])
    call = _activity(client, lead_id=lead["id"])

    res = _act(client, "leads", lead, "convert")
    assert res.status_code == 200, res.text
    assert res.json()["message"] == "Client créé : Fromagerie Mons"
    row = res.json()["row"]
    assert row["status"] == "converted" and row["client_id__label"] == "Fromagerie Mons" and row["_actions"] == []
    assert row["_locked"] == ("Prospect converti en client : il ne se modifie plus. Ses coordonnées sont désormais dans "
                              "la fiche du client (Ventes).")
    created = services.get_client(row["client_id"])
    assert {k: created[k] for k in ("name", "contact_name", "email", "phone", "city", "notes")} == {
        "name": "Fromagerie Mons", "contact_name": "Odile Mons", "email": "odile@fromagerie-mons.example",
        "phone": "04 65 71 80 12", "city": "Lyon", "notes": "Plateaux de fromages pour les entreprises."}
    assert _count("clients") == before + 1
    # ses opportunités et ses actions sans client sont rattachées au nouveau client ; les autres gardent le leur
    assert _get(client, "opportunities", without)["client_id"] == row["client_id"]
    assert _get(client, "opportunities", with_client)["client_id"] == nova
    assert _get(client, "opportunities", other)["client_id"] is None
    assert _get(client, "activities", call)["client_id__label"] == "Fromagerie Mons"
    # une seule conversion
    assert _error(_act(client, "leads", lead, "convert"), 409) == NOT_NOW
    assert _count("clients") == before + 1

    # même nom, autres majuscules et espaces : rattaché au client créé, sans doublon
    twin = _lead(client, "  fromagerie MONS ")
    assert twin["company"] == "fromagerie MONS"
    res = _act(client, "leads", twin, "convert").json()
    assert res["message"] == "Rattaché au client existant : Fromagerie Mons"
    assert res["row"]["client_id"] == row["client_id"] and _count("clients") == before + 1

    # le client est désormais désigné par le CRM : il ne se supprime plus
    res = client.delete(f"/api/data/sales/clients/{row['client_id']}")
    assert _error(res, 409) == ("Suppression impossible : cette fiche est utilisée ailleurs (opportunités : 1, "
                                "prospects : 2, actions commerciales : 1).")


def test_conversion_reuses_an_existing_client(client):
    before = _count("clients")
    nova = services.get_client(_client_id("Atelier Nova"))
    lead = _lead(client, "ATELIER NOVA", contact_name="Claire Dupuis", email="claire@atelier-nova.example", city="Paris")
    opportunity = _opportunity(client, "Nouvelle signalétique", lead_id=lead["id"])
    res = _act(client, "leads", lead, "convert").json()
    assert res["message"] == "Rattaché au client existant : Atelier Nova"
    assert res["row"]["client_id"] == nova["id"] and _count("clients") == before
    assert services.get_client(nova["id"]) == nova  # le client existant n'est pas modifié
    assert _get(client, "opportunities", opportunity)["client_id"] == nova["id"]
    # une nouvelle opportunité ou action d'un prospect converti prend son client
    later = _opportunity(client, "Plaques de porte", lead_id=lead["id"])
    assert later["client_id"] == nova["id"] and "create_quote" in later["_actions"]
    assert _activity(client, lead_id=lead["id"])["client_id"] == nova["id"]
    # sauf si un client est choisi
    kairos = _client_id("Kairos Conseil")
    assert _opportunity(client, "Pour Kairos", lead_id=lead["id"], client_id=kairos)["client_id"] == kairos


def test_conversion_needs_the_sales_module(client, restore_modules):
    lead = _lead(client)
    before = _count("clients")
    disable_module(client, "sales")
    res = _act(client, "leads", lead, "convert")
    assert _error(res) == "Activez le module Ventes pour convertir un prospect en client."
    row = _get(client, "leads", lead)
    assert row["status"] == "new" and "client_id" not in row and "convert" in row["_actions"]
    assert _count("clients") == before
    assert db.fetch_one("SELECT client_id FROM crm_leads WHERE id = ?", (lead["id"],))["client_id"] is None


def test_conversion_and_quote_need_the_right_to_write_in_sales(client):
    nova = _client_id("Atelier Nova")
    # rôle Commercial (écriture sur le CRM), mais seulement la lecture des Ventes
    make_member("crm-seul@test.local", "sales", {"sales": "read"})
    member = login_as("crm-seul@test.local")
    lead = _lead(member)
    opportunity = _opportunity(member, client_id=nova, amount=800)
    before, quotes = _count("clients"), _quotes()
    res = member.post(f"{BASE}/leads/{lead['id']}/actions/convert", json={})
    assert _error(res, 403) == ("Droits insuffisants : la conversion crée un client dans les Ventes, ce qui demande le droit "
                                "d'écriture sur ce module.")
    res = member.post(f"{BASE}/opportunities/{opportunity['id']}/actions/create_quote", json={})
    assert _error(res, 403) == "Droits insuffisants : créer un devis demande le droit d'écriture sur les Ventes."
    assert (_count("clients"), _quotes()) == (before, quotes)
    assert _get(client, "leads", lead)["status"] == "new" and _get(client, "opportunities", opportunity)["quote_id"] is None
    # un appel interne (script, démonstration) n'a pas d'utilisateur : rien à vérifier
    assert _run(OPPORTUNITIES, "create_quote", _get(client, "opportunities", opportunity)).startswith("Devis brouillon créé")
    assert _quotes() == quotes + 1


def test_simultaneous_actions_leave_no_duplicate(client):
    # le prospect vient d'être perdu par quelqu'un d'autre : la conversion calculée sur l'ancien état est refusée,
    # et le client qu'elle venait de créer est retiré
    lead = _lead(client)
    stale = entities.get_row(LEADS, lead["id"], MANAGE)
    _act(client, "leads", lead, "lost")
    before = _count("clients")
    with pytest.raises(Conflict, match=CHANGED):
        _run(LEADS, "convert", stale)
    assert _count("clients") == before and not _count("clients", "name = ?", ("Fromagerie Mons",))
    # le devis vient d'être créé par un autre clic : le second devis est retiré
    opportunity = _opportunity(client, client_id=_client_id("Atelier Nova"), amount=500)
    stale = entities.get_row(OPPORTUNITIES, opportunity["id"], MANAGE)
    _act(client, "opportunities", opportunity, "create_quote")
    quotes = _quotes()
    with pytest.raises(Conflict, match=CHANGED):
        _run(OPPORTUNITIES, "create_quote", stale)
    assert _quotes() == quotes
    # l'activité vient d'être faite
    activity = _activity(client)
    stale = entities.get_row(ACTIVITIES, activity["id"], MANAGE)
    _act(client, "activities", activity, "done")
    with pytest.raises(Conflict, match=CHANGED):
        _run(ACTIVITIES, "done", stale)


# ═════════════════════════════════════════════════════════════════════════
# Opportunités : numéro, probabilité, montant pondéré, validation
# ═════════════════════════════════════════════════════════════════════════
def test_opportunity_probability_and_weighted_amount(client):
    count = _count("crm_opportunities")
    nova = _client_id("Atelier Nova")
    first = _opportunity(client, "Flyers du salon", client_id=nova, amount="1 234,56", probability=33, code="PIRATE",
                         quote_id=42, weighted_amount=1)
    assert first["code"] == f"OPP-{today().year}-{count + 1:04d}"
    assert (first["stage"], first["probability"], first["amount"], first["weighted_amount"]) == ("prospecting", 33, 1234.56,
                                                                                              407.4)
    assert first["quote_id"] is None and first["quote_number"] == ""  # numéro et devis : remplis par le serveur
    assert first["client_id__label"] == "Atelier Nova" and first["lead_id"] is None
    second = _opportunity(client, "Sans montant", client_id=nova)
    assert second["code"] == f"OPP-{today().year}-{count + 2:04d}"
    assert (second["probability"], second["weighted_amount"]) == (10, None)  # pas de montant : rien à pondérer
    # à la création, sans probabilité : celle de l'étape
    for stage, expected in (("prospecting", 10), ("qualification", 25), ("proposal", 50), ("negotiation", 75)):
        row = _opportunity(client, stage, client_id=nova, stage=stage, amount=1000)
        assert (row["probability"], row["weighted_amount"]) == (expected, 10 * expected), stage
    # une probabilité saisie est gardée, zéro compris
    custom = _opportunity(client, "Probable", client_id=nova, stage="qualification", probability=60, amount=2000)
    assert (custom["probability"], custom["weighted_amount"]) == (60, 1200)
    zero = _opportunity(client, "Improbable", client_id=nova, stage="negotiation", probability=0, amount=500)
    assert (zero["probability"], zero["weighted_amount"]) == (0, 0)

    url = f"{BASE}/opportunities/{custom['id']}"
    # étape changée sans nouvelle probabilité : celle de la nouvelle étape (le formulaire renvoie l'ancienne valeur)
    moved = client.put(url, json={"stage": "proposal", "probability": 60}).json()
    assert (moved["stage"], moved["probability"], moved["weighted_amount"]) == ("proposal", 50, 1000)
    moved = client.put(url, json={"stage": "negotiation"}).json()
    assert (moved["probability"], moved["weighted_amount"]) == (75, 1500)
    # étape et probabilité changées ensemble : la probabilité saisie
    both = client.put(url, json={"stage": "proposal", "probability": 40}).json()
    assert (both["stage"], both["probability"], both["weighted_amount"]) == ("proposal", 40, 800)
    # même étape : la probabilité saisie ; effacée, celle de l'étape
    assert client.put(url, json={"probability": "33,5"}).json()["probability"] == 33.5
    cleared = client.put(url, json={"probability": None, "amount": "1 234,56"}).json()
    assert (cleared["probability"], cleared["weighted_amount"]) == (50, 617.28)
    # un autre champ modifié (étape renvoyée telle quelle) : la probabilité ne bouge pas
    client.put(url, json={"probability": 33})
    kept = client.put(url, json={"notes": "Relancer après le salon", "stage": "proposal"}).json()
    assert (kept["stage"], kept["probability"], kept["weighted_amount"]) == ("proposal", 33, 407.4)
    # la liste calcule les mêmes montants pondérés
    listed = {r["id"]: r for r in client.get(f"{BASE}/opportunities", params={"size": 200}).json()["rows"]}
    assert (listed[custom["id"]]["probability"], listed[custom["id"]]["weighted_amount"]) == (33, 407.4)
    assert listed[second["id"]]["weighted_amount"] is None and listed[zero["id"]]["weighted_amount"] == 0
    # au centime, la moitié vers le haut, comme une facture : 1 000,50 × 25 % = 250,125 → 250,13 (round() : 250,12)
    halves = _opportunity(client, "Demi-centime", client_id=nova, stage="qualification", amount="1 000,50")
    assert (halves["probability"], halves["weighted_amount"]) == (25, 250.13)

    # aperçu pendant la saisie : le serveur calcule, rien n'est enregistré
    total = _count("crm_opportunities")

    def preview(data, row_id=None):
        res = client.post(f"{BASE}/opportunities/preview", params={"id": row_id} if row_id else {}, json=data)
        assert res.status_code == 200, res.text
        return res.json()["computed"]

    assert preview({"amount": 2000, "stage": "negotiation"}) == {"weighted_amount": 1500, "quote_number": ""}
    assert preview({"amount": 2000, "stage": "qualification", "probability": 60})["weighted_amount"] == 1200
    assert preview({"amount": "1 000"})["weighted_amount"] == 100  # sans étape : découverte
    assert preview({}) == {"weighted_amount": None, "quote_number": ""}
    assert preview({"amount": "beaucoup", "probability": 50})["weighted_amount"] is None
    assert preview({"amount": 0.25, "stage": "proposal"})["weighted_amount"] == 0.13
    # fiche enregistrée (proposition, 33 %) : l'aperçu suit la règle de l'enregistrement, le formulaire renvoyant
    # l'ancienne probabilité quand seule l'étape change
    form = {"title": "Probable", "client_id": nova, "amount": 1234.56, "stage": "proposal", "probability": 33}
    assert preview(form, custom["id"])["weighted_amount"] == 407.4
    assert preview({**form, "stage": "negotiation"}, custom["id"])["weighted_amount"] == 925.92  # 75 %
    assert preview({**form, "stage": "negotiation", "probability": 40}, custom["id"])["weighted_amount"] == 493.82
    assert preview({**form, "probability": None}, custom["id"])["weighted_amount"] == 617.28  # effacée : 50 %
    assert _count("crm_opportunities") == total
    assert _get(client, "opportunities", custom)["probability"] == 33  # rien n'est enregistré
    # l'enregistrement donne ce que l'aperçu annonçait
    saved = client.put(url, json={**form, "stage": "negotiation"}).json()
    assert (saved["stage"], saved["probability"], saved["weighted_amount"]) == ("negotiation", 75, 925.92)


def test_opportunity_validation(client):
    nova = _client_id("Atelier Nova")

    def post(data):
        return client.post(f"{BASE}/opportunities", json={"title": "Affiche", **data})

    for data, message in (
        ({}, NO_LINK),
        ({"client_id": None, "lead_id": None}, NO_LINK),
        ({"client_id": nova, "title": " "}, "Intitulé : obligatoire."),
        ({"client_id": nova, "amount": -1}, "Montant HT : 0 au minimum."),
        ({"client_id": nova, "amount": "cher"}, "Montant HT : nombre attendu."),
        ({"client_id": nova, "probability": 101}, "Probabilité : 100 au maximum."),
        ({"client_id": nova, "probability": -5}, "Probabilité : 0 au minimum."),
        ({"client_id": nova, "stage": "signed"}, "Étape : valeur non proposée."),
        ({"client_id": nova, "stage": None}, "Étape : obligatoire."),
        ({"client_id": nova, "stage": "won"}, CLOSE_BY_BUTTON),
        ({"client_id": nova, "stage": "lost"}, CLOSE_BY_BUTTON),
        ({"client_id": nova, "expected_close": "31/02/2026"}, "Clôture prévue : date invalide."),
        ({"client_id": 999999}, "Client : fiche introuvable."),
        ({"lead_id": 999999}, "Prospect : fiche introuvable."),
        ({"lead_id": 10**20}, "Prospect : nombre hors limites."),
    ):
        assert _error(post(data)) == message, data
    # un prospect seul, ou un client seul, suffit
    assert post({"lead_id": _lead(client)["id"]}).status_code == 201
    opportunity = post({"client_id": nova, "expected_close": "15/12/2026"}).json()
    assert opportunity["expected_close"] == "2026-12-15"
    url = f"{BASE}/opportunities/{opportunity['id']}"
    assert _error(client.put(url, json={"stage": "won"})) == CLOSE_BY_BUTTON
    assert _error(client.put(url, json={"client_id": None})) == NO_LINK
    assert _get(client, "opportunities", opportunity)["stage"] == "prospecting"
    assert client.get(f"{BASE}/opportunities", params={"f_stage": "signed"}).status_code == 400


def test_won_and_lost_lock_the_opportunity(client):
    nova = _client_id("Atelier Nova")
    opportunity = _opportunity(client, "Kakémonos", client_id=nova, stage="proposal", amount=1500)
    assert set(opportunity["_actions"]) == {"create_quote", "won", "lost"} and opportunity["_deletable"] is True
    url = f"{BASE}/opportunities/{opportunity['id']}"
    won = _act(client, "opportunities", opportunity, "won").json()
    assert won["message"] == f"Opportunité {opportunity['code']} gagnée."
    row = won["row"]
    assert (row["stage"], row["probability"], row["weighted_amount"]) == ("won", 100, 1500)
    assert row["_locked"] == "Opportunité gagnée : elle ne se modifie plus."
    assert row["_actions"] == ["create_quote"]  # pas encore de devis : il reste possible
    assert _error(client.put(url, json={"notes": "x"}), 409) == row["_locked"]
    for action in ("won", "lost"):
        assert _error(_act(client, "opportunities", opportunity, action), 409) == NOT_NOW, action
    assert row["_deletable"] is False
    assert _error(client.delete(url), 409) == "Une opportunité gagnée ne se supprime pas : elle fait partie de l'historique des ventes."

    stand = _opportunity(client, "Stand du salon", client_id=nova, stage="negotiation", amount=4000,
                         lost_reason="Budget reporté à l'an prochain")
    lost = _act(client, "opportunities", stand, "lost").json()
    assert lost["message"] == f"Opportunité {stand['code']} perdue."
    row = lost["row"]
    assert (row["stage"], row["probability"], row["weighted_amount"]) == ("lost", 0, 0)
    assert row["lost_reason"] == "Budget reporté à l'an prochain"
    assert row["_locked"] == "Opportunité perdue : elle ne se modifie plus." and row["_actions"] == []
    for action in ("won", "lost", "create_quote"):
        assert _error(_act(client, "opportunities", stand, action), 409) == NOT_NOW, action
    assert client.put(f"{BASE}/opportunities/{stand['id']}", json={"lost_reason": "x"}).status_code == 409
    assert row["_deletable"] is True  # perdue : verrouillée, mais supprimable
    assert client.delete(f"{BASE}/opportunities/{stand['id']}").status_code == 204

    # une opportunité désignée par une action commerciale ne se supprime pas
    busy = _opportunity(client, "Occupée", client_id=nova)
    _activity(client, opportunity_id=busy["id"])
    res = client.delete(f"{BASE}/opportunities/{busy['id']}")
    assert _error(res, 409) == "Suppression impossible : cette fiche est utilisée ailleurs (actions commerciales : 1)."


# ═════════════════════════════════════════════════════════════════════════
# Devis dans les Ventes
# ═════════════════════════════════════════════════════════════════════════
def test_create_quote(client):
    nova = _client_id("Atelier Nova")
    listed = len(client.get("/api/invoices", params={"kind": "quote"}).json())
    opportunity = _opportunity(client, "Signalétique de l'atelier", client_id=nova, amount=1850.5)
    assert opportunity["stage"] == "prospecting" and "create_quote" in opportunity["_actions"]
    url = f"{BASE}/opportunities/{opportunity['id']}"
    res = _act(client, "opportunities", opportunity, "create_quote")
    assert res.status_code == 200, res.text
    assert res.json()["message"] == "Devis brouillon créé dans Ventes → Factures et devis."
    row = res.json()["row"]
    assert row["quote_number"] == "brouillon" and row["quote_id"] and "create_quote" not in row["_actions"]
    # pas encore à l'étape « Proposition » : elle y passe, avec sa probabilité
    assert (row["stage"], row["probability"], row["weighted_amount"]) == ("proposal", 50, 925.25)
    quotes = client.get("/api/invoices", params={"kind": "quote"}).json()
    assert len(quotes) == listed + 1
    quote = next(q for q in quotes if q["id"] == row["quote_id"])
    assert (quote["kind"], quote["status"], quote["client_id"], quote["title"]) == ("quote", "draft", nova,
                                                                                  "Signalétique de l'atelier")
    assert quote["subtotal"] == 1850.5 and quote["number"] is None
    assert [(i["description"], i["quantity"], i["unit_price"]) for i in quote["items"]] == [
        ("Signalétique de l'atelier", 1, 1850.5)]
    assert _error(_act(client, "opportunities", opportunity, "create_quote"), 409) == NOT_NOW  # un seul devis
    # le devis émis dans les Ventes : son numéro s'affiche
    issued = client.post(f"/api/invoices/{quote['id']}/finalize")
    assert issued.status_code == 200, issued.text
    number = issued.json()["number"]
    assert number.startswith(f"DEVIS-{today().year}-") and client.get(url).json()["quote_number"] == number
    listed_row = next(r for r in client.get(f"{BASE}/opportunities", params={"size": 200}).json()["rows"]
                      if r["id"] == opportunity["id"])
    assert listed_row["quote_number"] == number

    # déjà en négociation : l'étape ne recule pas ; gagnée sans devis : le devis reste possible
    late = _opportunity(client, "Bâches", client_id=nova, stage="negotiation", amount=600)
    row = _act(client, "opportunities", late, "create_quote").json()["row"]
    assert (row["stage"], row["probability"], row["quote_number"]) == ("negotiation", 75, "brouillon")
    won = _opportunity(client, "Gagnée sans devis", client_id=nova, stage="qualification", amount=300)
    _act(client, "opportunities", won, "won")
    row = _act(client, "opportunities", won, "create_quote").json()["row"]
    assert (row["stage"], row["probability"], row["quote_number"]) == ("won", 100, "brouillon")

    # sans client (prospect seul) ou perdue : pas de devis
    lead_only = _opportunity(client, "Sans client", lead_id=_lead(client)["id"])
    assert "create_quote" not in lead_only["_actions"]
    assert _error(_act(client, "opportunities", lead_only, "create_quote"), 409) == NOT_NOW
    with pytest.raises(ValueError, match="Client : choisissez un client avant de créer le devis."):
        _run(OPPORTUNITIES, "create_quote", entities.get_row(OPPORTUNITIES, lead_only["id"], MANAGE))
    lost = _opportunity(client, "Perdue", client_id=nova)
    _act(client, "opportunities", lost, "lost")
    assert "create_quote" not in _get(client, "opportunities", lost)["_actions"]

    # brouillon de devis supprimé dans les Ventes : l'opportunité peut en créer un autre
    assert client.delete(f"/api/invoices/{row['quote_id']}").status_code == 204
    again = _get(client, "opportunities", won)
    assert again["quote_number"] == "" and "create_quote" in again["_actions"]
    renewed = _act(client, "opportunities", won, "create_quote").json()["row"]
    assert renewed["quote_number"] == "brouillon" and renewed["quote_id"] != row["quote_id"]


def test_no_quote_for_a_vanished_client(client):
    customer = client.post("/api/data/sales/clients", json={"name": "Client éphémère"}).json()
    opportunity = _opportunity(client, client_id=customer["id"], amount=100)
    db.execute("DELETE FROM clients WHERE id = ?", (customer["id"],))  # supprimé hors du moteur (pas de clé étrangère)
    row = _get(client, "opportunities", opportunity)
    assert row["client_id"] == customer["id"] and row["client_id__label"] is None
    quotes = _quotes()
    res = _act(client, "opportunities", opportunity, "create_quote")
    assert _error(res) == "Client : choisissez un client avant de créer le devis."
    assert _quotes() == quotes and _get(client, "opportunities", opportunity)["stage"] == "prospecting"


def test_create_quote_needs_the_sales_module(client, restore_modules):
    nova = _client_id("Atelier Nova")
    opportunity = _opportunity(client, "Affiches", client_id=nova, amount=500)
    quotes = _quotes()
    disable_module(client, "sales")
    row = _get(client, "opportunities", opportunity)
    assert "client_id" not in row and "create_quote" not in row["_actions"]
    assert _error(_act(client, "opportunities", opportunity, "create_quote"), 409) == NOT_NOW
    # appelée directement (script), l'action le dit clairement
    with pytest.raises(ValueError, match="Activez le module Ventes pour créer un devis."):
        _run(OPPORTUNITIES, "create_quote", {**row, "client_id": nova})
    assert _quotes() == quotes
    assert db.fetch_one("SELECT quote_id FROM crm_opportunities WHERE id = ?", (opportunity["id"],))["quote_id"] is None


# ═════════════════════════════════════════════════════════════════════════
# Actions commerciales
# ═════════════════════════════════════════════════════════════════════════
def test_activity_done_and_overdue(client):
    today_call = _activity(client, "Appeler Odile", done_on=_day(-3), overdue=True)
    assert (today_call["kind"], today_call["due_date"], today_call["done"], today_call["done_on"]) == ("call", _day(), False, None)
    assert today_call["overdue"] is False and today_call["_actions"] == ["done"]  # échéance aujourd'hui : pas en retard
    late = _activity(client, "Relancer Odile", kind="email", due_date=_day(-1))
    assert late["overdue"] is True
    undated = _activity(client, "Sans échéance", kind="task", due_date=None)
    assert undated["due_date"] is None and undated["overdue"] is False

    res = _act(client, "activities", late, "done").json()
    assert res["message"] == "Action « Relancer Odile » marquée comme faite."
    row = res["row"]
    assert (row["done"], row["done_on"], row["overdue"], row["_actions"]) == (True, _day(), False, [])
    assert _error(_act(client, "activities", late, "done"), 409) == NOT_NOW
    # une action faite reste modifiable : décochée, elle redevient à faire (et en retard)
    url = f"{BASE}/activities/{late['id']}"
    reopened = client.put(url, json={"done": False}).json()
    assert (reopened["done"], reopened["done_on"], reopened["overdue"], reopened["_actions"]) == (False, None, True, ["done"])
    ticked = client.put(url, json={"done": True, "notes": "Rappel fait"}).json()
    assert (ticked["done"], ticked["done_on"], ticked["overdue"]) == (True, _day(), False)
    db.execute("UPDATE crm_activities SET done_on = ? WHERE id = ?", (_day(-1), late["id"]))
    unchanged = client.put(url, json={"done": True, "subject": "Relancer Odile Mons"}).json()
    assert unchanged["done_on"] == _day(-1)  # déjà faite : la date reste
    assert client.put(url, json={"done": None}).json()["done"] is True  # case vide : la valeur enregistrée
    assert _activity(client, "Déjà faite", done=True)["done_on"] == _day()

    pending = client.get(f"{BASE}/activities", params={"f_done": "0", "size": 200}).json()["rows"]
    assert {today_call["id"], undated["id"]} <= {r["id"] for r in pending} and late["id"] not in {r["id"] for r in pending}
    assert not [r for r in pending if r["done"]]
    # à faire d'abord, puis par échéance (les plus anciennes en tête)
    rows = client.get(f"{BASE}/activities", params={"size": 200}).json()["rows"]
    flags = [r["done"] for r in rows]
    assert flags == sorted(flags)
    dates = [r["due_date"] for r in rows if not r["done"]]
    assert dates == sorted(dates, key=lambda d: (d is not None, d or ""))
    emails = client.get(f"{BASE}/activities", params={"f_kind": "email", "size": 200}).json()["rows"]
    assert late["id"] in {r["id"] for r in emails} and {r["kind"] for r in emails} == {"email"}

    def preview(data):
        return client.post(f"{BASE}/activities/preview", json=data).json()["computed"]

    assert preview({"due_date": _day(-2)}) == {"overdue": True}
    assert preview({"due_date": _day(-2), "done": True}) == {"overdue": False}
    assert preview({"due_date": _day()}) == {"overdue": False}
    assert preview({}) == {"overdue": False}
    for bad, message in (
        ({}, "Objet : obligatoire."),
        ({"subject": "x", "kind": "fax"}, "Type : valeur non proposée."),
        ({"subject": "x", "kind": None}, "Type : obligatoire."),
        ({"subject": "x", "due_date": "demain"}, "Échéance : date invalide."),
        ({"subject": "x", "done": "peut-être"}, "Faite : oui ou non attendu."),
        ({"subject": "x", "opportunity_id": 999999}, "Opportunité : fiche introuvable."),
        ({"subject": "x", "lead_id": 999999}, "Prospect : fiche introuvable."),
        ({"subject": "x", "client_id": 999999}, "Client : fiche introuvable."),
    ):
        assert _error(client.post(f"{BASE}/activities", json=bad)) == message, bad


def test_activity_takes_the_opportunity_links(client):
    nova, kairos = _client_id("Atelier Nova"), _client_id("Kairos Conseil")
    lead = _lead(client)
    opportunity = _opportunity(client, lead_id=lead["id"], client_id=nova)
    meeting = _activity(client, "Dégustation chez le client", kind="meeting", opportunity_id=opportunity["id"])
    assert (meeting["lead_id"], meeting["client_id"], meeting["opportunity_id__label"]) == (lead["id"], nova,
                                                                                            "Plateaux de fêtes")
    assert meeting["lead_id__label"] == "Fromagerie Mons" and meeting["client_id__label"] == "Atelier Nova"
    # des valeurs choisies sont gardées
    other = _lead(client, "Autre prospect")
    chosen = _activity(client, opportunity_id=opportunity["id"], lead_id=other["id"], client_id=kairos)
    assert (chosen["lead_id"], chosen["client_id"]) == (other["id"], kairos)
    # un prospect effacé le reste tant que l'opportunité ne change pas
    url = f"{BASE}/activities/{meeting['id']}"
    cleared = client.put(url, json={"lead_id": None}).json()
    assert cleared["lead_id"] is None and cleared["opportunity_id"] == opportunity["id"]
    # changer d'opportunité reprend ses liens s'ils sont vides
    second = _opportunity(client, "Coffrets", lead_id=other["id"], client_id=kairos)
    moved = client.put(url, json={"opportunity_id": second["id"]}).json()
    assert (moved["lead_id"], moved["client_id"]) == (other["id"], nova)  # le client choisi avant reste


# ═════════════════════════════════════════════════════════════════════════
# Vues en colonnes, export
# ═════════════════════════════════════════════════════════════════════════
def test_board_views(client):
    nova = _client_id("Atelier Nova")
    _act(client, "opportunities", _opportunity(client, "Perdue", client_id=nova, amount=700), "lost")
    board = client.get(f"{BASE}/opportunities/board").json()
    assert board["field"] == "stage" and board["amount_field"] == "amount"
    assert [c["value"] for c in board["columns"]] == STAGES
    rows = client.get(f"{BASE}/opportunities", params={"size": 200}).json()["rows"]
    for column in board["columns"]:
        mine = [r for r in rows if r["stage"] == column["value"]]
        assert column["count"] == len(mine) and {r["id"] for r in column["rows"]} == {r["id"] for r in mine}
        assert column["amount"] == cents(sum(r["amount"] or 0 for r in mine))
    assert next(c for c in board["columns"] if c["value"] == "lost")["count"] >= 1
    filtered = client.get(f"{BASE}/opportunities/board", params={"f_client_id": nova}).json()
    assert sum(c["count"] for c in filtered["columns"]) == len([r for r in rows if r["client_id"] == nova])
    leads = client.get(f"{BASE}/leads/board").json()
    assert leads["field"] == "status" and leads["amount_field"] is None
    assert [c["value"] for c in leads["columns"]] == ["new", "contacted", "qualified", "converted", "lost"]
    total = client.get(f"{BASE}/leads").json()["total"]
    assert sum(c["count"] for c in leads["columns"]) == total
    assert client.get(f"{BASE}/activities/board").status_code == 404  # pas de vue en colonnes


def test_export_lists_weighted_amounts(client):
    opportunity = _opportunity(client, "Export pondéré", client_id=_client_id("Atelier Nova"), stage="qualification",
                               amount="1 234,56", expected_close="2026-12-15")
    res = client.get(f"{BASE}/opportunities/export", params={"q": "Export pondéré"})
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    header, *rows = list(csv.reader(io.StringIO(res.text.lstrip("﻿")), delimiter=";"))
    [row] = rows
    cells = dict(zip(header, row, strict=True))
    assert cells["Numéro"] == opportunity["code"] and cells["Client"] == "Atelier Nova" and cells["Étape"] == "Qualification"
    assert (cells["Montant HT"], cells["Probabilité"], cells["Montant pondéré"]) == ("1234,56", "25", "308,64")
    assert cells["Clôture prévue"] == "15/12/2026" and cells["Devis"] == ""
    english = client.get(f"{BASE}/opportunities/export", params={"q": "Export pondéré", "lang": "en"}).text.lstrip("﻿")
    header, row = list(csv.reader(io.StringIO(english)))
    assert dict(zip(header, row, strict=True))["Weighted amount"] == "308.64"


# ═════════════════════════════════════════════════════════════════════════
# Droits, activation
# ═════════════════════════════════════════════════════════════════════════
def test_readonly_role_cannot_write(client):
    lead = _lead(client)
    opportunity = _opportunity(client, lead_id=lead["id"], amount=900)
    activity = _activity(client, lead_id=lead["id"])
    make_member("lecture-crm@test.local", "readonly")
    reader = login_as("lecture-crm@test.local")
    for entity, row in (("leads", lead), ("opportunities", opportunity), ("activities", activity)):
        base = f"{BASE}/{entity}"
        assert reader.get(base).status_code == 200 and reader.get(f"{base}/export").status_code == 200
        record = reader.get(f"{base}/{row['id']}").json()
        assert record["_actions"] == [] and record["_deletable"] is False
        assert reader.post(base, json={"company": "x", "title": "x", "subject": "x"}).status_code == 403
        assert reader.put(f"{base}/{row['id']}", json={"notes": "x"}).status_code == 403
        assert reader.post(f"{base}/preview", json={}).status_code == 403
        assert reader.delete(f"{base}/{row['id']}").status_code == 403
        meta = reader.get("/api/meta").json()["entities"][f"crm.{entity}"]
        assert not (meta["can_create"] or meta["can_edit"] or meta["can_delete"])
    assert reader.get(f"{BASE}/opportunities/board").status_code == 200
    for entity, row, actions in (("leads", lead, ("contacted", "qualify", "convert", "lost")),
                                 ("opportunities", opportunity, ("create_quote", "won", "lost")),
                                 ("activities", activity, ("done",))):
        for action in actions:
            assert reader.post(f"{BASE}/{entity}/{row['id']}/actions/{action}", json={}).status_code == 403, action
    assert _get(client, "leads", lead)["status"] == "new" and _get(client, "activities", activity)["done"] is False
    home = reader.get("/api/home").json()
    assert {"crm.pipeline", "crm.open_opportunities", "crm.activities_due"} <= {k["key"] for k in home["kpis"]}
    assert "crm.new_opportunity" not in {s["key"] for s in home["shortcuts"]}  # raccourci : niveau écriture


def test_sales_role_runs_the_crm(client):
    make_member("commercial-crm@test.local", "sales")
    seller = login_as("commercial-crm@test.local")
    meta = seller.get("/api/meta").json()
    assert meta["levels"]["crm"] == 2 and "crm" in [m["key"] for m in meta["modules"]]
    opportunities = meta["entities"]["crm.opportunities"]
    assert opportunities["can_create"] and opportunities["can_edit"] and not opportunities["can_delete"]
    # choix d'un client depuis le formulaire d'une opportunité
    options = seller.get("/api/data/sales/clients/options", params={"q": "nova", "for": "crm.opportunities.client_id"})
    assert options.status_code == 200 and options.json()[0]["label"] == "Atelier Nova"
    lead = _lead(seller)
    opportunity = _opportunity(seller, lead_id=lead["id"], amount=800)
    _act(seller, "leads", lead, "contacted")
    converted = _act(seller, "leads", lead, "convert")
    assert converted.status_code == 200 and converted.json()["message"] == "Client créé : Fromagerie Mons"
    quote = _act(seller, "opportunities", opportunity, "create_quote")
    assert quote.status_code == 200 and quote.json()["row"]["quote_number"] == "brouillon"
    assert _act(seller, "opportunities", opportunity, "won").json()["row"]["stage"] == "won"
    done = _act(seller, "activities", _activity(seller, lead_id=lead["id"]), "done")
    assert done.status_code == 200 and done.json()["row"]["done"] is True
    # supprimer demande le niveau gestion
    spare = _opportunity(seller, "À supprimer", lead_id=lead["id"])
    assert seller.delete(f"{BASE}/opportunities/{spare['id']}").status_code == 403
    assert seller.delete(f"{BASE}/leads/{lead['id']}").status_code == 403
    assert client.delete(f"{BASE}/opportunities/{spare['id']}").status_code == 204
    home = seller.get("/api/home").json()
    assert {"crm.pipeline", "crm.open_opportunities", "crm.activities_due"} <= {k["key"] for k in home["kpis"]}
    assert "crm.new_opportunity" in {s["key"] for s in home["shortcuts"]}
    # un acheteur n'a pas accès au CRM
    make_member("acheteur-crm@test.local", "buyer")
    buyer = login_as("acheteur-crm@test.local")
    assert buyer.get(f"{BASE}/opportunities").status_code == 403
    assert not [k for k in buyer.get("/api/home").json()["kpis"] if k["module"] == "crm"]


def test_disabled_crm_disappears(client, restore_modules):
    customer = client.post("/api/data/sales/clients", json={"name": "Client du CRM"}).json()
    lead = _lead(client)
    opportunity = _opportunity(client, lead_id=lead["id"], client_id=customer["id"])
    disable_module(client, "crm")
    assert client.get(f"{BASE}/leads").status_code == 404
    assert client.get(f"{BASE}/opportunities/{opportunity['id']}").status_code == 404
    assert client.post(f"{BASE}/activities", json={"subject": "x"}).status_code == 404
    assert client.post(f"{BASE}/leads/{lead['id']}/actions/convert", json={}).status_code == 404
    meta = client.get("/api/meta").json()
    assert "crm" not in [m["key"] for m in meta["modules"]] and not [k for k in meta["entities"] if k.startswith("crm.")]
    home = client.get("/api/home").json()
    assert not [k for k in home["kpis"] if k["module"] == "crm"] and not [s for s in home["shortcuts"] if s["module"] == "crm"]
    assert client.get("/api/data/sales/clients").status_code == 200
    # ses données restent et protègent toujours le client qu'elles désignent
    res = client.delete(f"/api/data/sales/clients/{customer['id']}")
    assert _error(res, 409) == "Suppression impossible : cette fiche est utilisée ailleurs (opportunités : 1)."
    assert client.put("/api/settings/modules/crm", json={"enabled": True}).status_code == 200
    assert _get(client, "opportunities", opportunity)["code"] == opportunity["code"]


def test_crm_works_without_sales(client, restore_modules):
    nova = _client_id("Atelier Nova")
    client_only = _opportunity(client, "Client seul", client_id=nova, amount=1000)
    lead = _lead(client)
    disable_module(client, "sales")
    meta = client.get("/api/meta").json()["entities"]
    for key in ("crm.opportunities", "crm.leads", "crm.activities"):
        assert "client_id" not in [f["name"] for f in meta[key]["fields"]], key
    # une opportunité rattachée à un client seul reste modifiable : son client compte toujours
    edited = client.put(f"{BASE}/opportunities/{client_only['id']}", json={"title": "Client seul, renommé", "amount": 1200})
    assert edited.status_code == 200, edited.text
    assert edited.json()["weighted_amount"] == 120 and "client_id" not in edited.json()
    assert db.fetch_one("SELECT client_id FROM crm_opportunities WHERE id = ?", (client_only["id"],))["client_id"] == nova
    # une nouvelle opportunité demande un prospect (le client envoyé est ignoré : le champ n'existe plus)
    assert _error(client.post(f"{BASE}/opportunities", json={"title": "x", "client_id": nova})) == (
        "Prospect : choisissez un prospect (pour choisir un client, activez le module Ventes).")
    with_lead = _opportunity(client, "Avec prospect", lead_id=lead["id"], amount=500)
    assert with_lead["weighted_amount"] == 50 and "client_id" not in with_lead and "create_quote" not in with_lead["_actions"]
    meeting = _activity(client, opportunity_id=client_only["id"])
    assert "client_id" not in meeting and meeting["lead_id"] is None
    assert db.fetch_one("SELECT client_id FROM crm_activities WHERE id = ?", (meeting["id"],))["client_id"] is None
    for entity in ("leads", "opportunities", "activities"):
        assert client.get(f"{BASE}/{entity}").status_code == 200 and client.get(f"{BASE}/{entity}/export").status_code == 200
    assert client.get(f"{BASE}/opportunities/board").status_code == 200
    kpis = {k["key"]: k for k in client.get("/api/home").json()["kpis"]}
    assert {"crm.pipeline", "crm.open_opportunities", "crm.activities_due"} <= set(kpis)
    assert _act(client, "opportunities", with_lead, "won").json()["row"]["stage"] == "won"
    # les Ventes réactivées : le client réapparaît
    assert client.put("/api/settings/modules/sales", json={"enabled": True}).status_code == 200
    assert _get(client, "opportunities", client_only)["client_id__label"] == "Atelier Nova"


# ═════════════════════════════════════════════════════════════════════════
# Chiffres clés et « Mes vues »
# ═════════════════════════════════════════════════════════════════════════
def test_home_kpis_follow_the_pipeline(client):
    def kpis():
        return {k["key"]: k for k in client.get("/api/home").json()["kpis"]}

    start = kpis()
    pipeline, opened, due = start["crm.pipeline"], start["crm.open_opportunities"], start["crm.activities_due"]
    assert (pipeline["unit"], pipeline["path"]) == ("money", "/crm/opportunites")
    assert (opened["unit"], opened["path"]) == ("count", "/crm/opportunites?view=board")  # une colonne par étape
    assert (due["path"], due["label"]) == ("/crm/actions?f_done=0", ["Actions commerciales à traiter", "Sales activities due"])
    shortcut = next(s for s in client.get("/api/home").json()["shortcuts"] if s["key"] == "crm.new_opportunity")
    assert shortcut["path"] == "/crm/opportunites?new=1" and shortcut["label"] == ["Nouvelle opportunité", "New opportunity"]
    # chaque chiffre clé correspond à la liste qu'il ouvre
    rows = client.get(f"{BASE}/opportunities", params={"size": 200}).json()["rows"]
    open_rows = [r for r in rows if r["stage"] not in ("won", "lost")]
    assert pipeline["value"] == cents(sum(r["weighted_amount"] or 0 for r in open_rows))
    assert pipeline["count"] == opened["value"] == opened["count"] == len(open_rows)
    pending = client.get(f"{BASE}/activities", params={"f_done": "0", "size": 200}).json()["rows"]
    assert due["value"] == len([r for r in pending if r["due_date"] and r["due_date"] <= _day()])

    nova = _client_id("Atelier Nova")
    a = _opportunity(client, "A", client_id=nova, stage="negotiation", amount=1000)  # 750 pondérés
    b = _opportunity(client, "B", client_id=nova, amount=999.99)                    # 10 % : 100,00
    c = _opportunity(client, "C", client_id=nova)                                    # sans montant : comptée, rien pondéré
    d = _opportunity(client, "D", client_id=nova, stage="proposal", amount=0.25)    # 0,125 → 0,13
    e = _opportunity(client, "E", client_id=nova, stage="qualification", amount=1000.5)  # 250,125 → 250,13
    now = kpis()
    assert now["crm.pipeline"]["value"] == cents(pipeline["value"] + 1100.26)  # round() aurait donné 1 100,24
    assert now["crm.pipeline"]["count"] == now["crm.open_opportunities"]["value"] == opened["value"] + 5
    _act(client, "opportunities", a, "won")
    for lost in (b, d, e):
        _act(client, "opportunities", lost, "lost")
    end = kpis()
    assert end["crm.pipeline"]["value"] == pipeline["value"] and end["crm.open_opportunities"]["value"] == opened["value"] + 1
    assert _get(client, "opportunities", c)["stage"] == "prospecting"

    _activity(client, "Aujourd'hui")                         # échéance aujourd'hui : à traiter
    _activity(client, "Hier", due_date=_day(-1))             # en retard : à traiter
    _activity(client, "Demain", due_date=_day(1))            # pas encore
    _activity(client, "Sans échéance", due_date=None)        # pas d'échéance
    _activity(client, "Faite", due_date=_day(-2), done=True)  # faite
    after = kpis()["crm.activities_due"]
    assert after["value"] == after["count"] == due["value"] + 2 and after["alert"] is True

    # base vide : tout vaut zéro, sans alerte
    for table in ("crm_activities", "crm_opportunities", "crm_leads"):
        db.execute(f"DELETE FROM {table}")
    empty = kpis()
    assert [(empty[f"crm.{k}"]["value"], empty[f"crm.{k}"]["count"]) for k in ("pipeline", "open_opportunities",
                                                                                "activities_due")] == [(0, 0)] * 3
    assert empty["crm.activities_due"]["alert"] is False


def test_kpis_are_offered_in_my_views(client):
    """« Mes vues » reconnaît un chiffre clé quand la demande cite son libellé : chaque libellé nomme ce qu'il compte,
    et les demandes sur d'autres sujets (factures, devis, commandes) ne font pas apparaître le CRM."""
    def metrics(text):
        widgets = dashboard.compose_offline(text, {})["spec"]["widgets"]
        return [w["params"]["metric"] for w in widgets if w["source"] == "kpi"]

    module = registry.get("crm")
    assert [k.key for k in module.kpis] == ["pipeline", "open_opportunities", "activities_due"]
    for kpi in module.kpis:
        for label in kpi.label:
            assert f"crm.{kpi.key}" in metrics(f"Montre-moi : {label.lower()}"), label
    for text in ("mes factures en retard", "le total en retard", "mes devis en attente", "mes commandes à livrer",
                 "show me an overview of my sales", "combien j'ai encaissé ce mois-ci"):
        assert not [m for m in metrics(text) if m.startswith("crm.")], text
    # de bout en bout : la demande devient une carte, calculée par le module
    res = client.post("/api/dashboards/compose", json={"text": "Montre-moi le pipeline commercial pondéré"})
    [card] = [w for w in res.json()["view"]["widgets"] if w["source"] == "kpi"]
    home = {k["key"]: k for k in client.get("/api/home").json()["kpis"]}
    assert card["params"]["metric"] == "crm.pipeline" and card["data"]["value"] == home["crm.pipeline"]["value"]
    assert card["data"]["unit"] == "money" and card["data"]["path"] == "/crm/opportunites"
    # sans accès au CRM, ni la demande ni une vue enregistrée ne montrent ces chiffres
    make_member("acheteur-vues@test.local", "buyer")
    buyer = login_as("acheteur-vues@test.local")
    res = buyer.post("/api/dashboards/compose", json={"text": "Montre-moi le pipeline commercial pondéré"}).json()
    assert not [w for w in res["view"]["widgets"] if w["params"].get("metric", "").startswith("crm.")]
    hidden = buyer.post("/api/dashboards/render", json={"spec": {"widgets": [
        {"source": "kpi", "params": {"metric": "crm.activities_due"}}]}}).json()
    assert hidden["widgets"] == [] and hidden["hidden"] == 1


# ═════════════════════════════════════════════════════════════════════════
# Démonstration
# ═════════════════════════════════════════════════════════════════════════
def test_demo_data(client):
    year = today().year
    leads = {r["company"]: r for r in client.get(f"{BASE}/leads", params={"size": 200}).json()["rows"]}
    assert {name: (r["status"], r["source"], r["city"]) for name, r in leads.items()} == {
        "Brasserie des Canuts": ("new", "website", "Lyon"),
        "Librairie Passages": ("qualified", "referral", "Lyon"),
        "Cave Saint-Jean": ("contacted", "event", "Lyon"),
        "Studio Kinema": ("lost", "cold", "Villeurbanne"),
        "Pixel & Co Studio": ("converted", "social", "Bordeaux"),
    }
    assert all(r["email"].endswith(".example") for r in leads.values())
    pixel = leads["Pixel & Co Studio"]
    assert (pixel["client_id"], pixel["client_id__label"]) == (_client_id("Pixel & Co"), "Pixel & Co")
    assert [r["company"] for r in leads.values() if r["client_id"]] == ["Pixel & Co Studio"]

    opportunities = {r["title"]: r for r in client.get(f"{BASE}/opportunities", params={"size": 200}).json()["rows"]}
    expected = {
        "Signalétique du showroom": ("Atelier Nova", None, "negotiation", 3200, 75, 2400),
        f"Rapport annuel {year}": ("Kairos Conseil", None, "proposal", 4800, 50, 2400),
        "Identité visuelle": (None, "Librairie Passages", "qualification", 2400, 25, 600),
        "Étiquettes de bières": (None, "Brasserie des Canuts", "prospecting", 1800, 10, 180),
        "Catalogue printemps": ("Maison Verde", None, "won", 2600, 100, 2600),
    }
    assert {title: (r["client_id__label"], r["lead_id__label"], r["stage"], r["amount"], r["probability"],
                    r["weighted_amount"]) for title, r in opportunities.items()} == expected
    assert all(r["code"].startswith(f"OPP-{year}-") and r["quote_id"] is None for r in opportunities.values())
    assert opportunities["Catalogue printemps"]["expected_close"] == _day(-5)
    assert all(r["expected_close"] > _day() for r in opportunities.values() if r["stage"] != "won")

    activities = {r["kind"]: r for r in client.get(f"{BASE}/activities", params={"size": 200}).json()["rows"]}
    assert set(activities) == {"call", "meeting", "email", "task"}
    call, meeting, email, task = (activities[k] for k in ("call", "meeting", "email", "task"))
    assert (call["due_date"], call["done"], call["overdue"], call["lead_id__label"]) == (_day(1), False, False,
                                                                                       "Brasserie des Canuts")
    assert (meeting["due_date"], meeting["overdue"], meeting["client_id__label"]) == (_day(), False, "Atelier Nova")
    assert (email["due_date"], email["overdue"], email["client_id__label"]) == (_day(-3), True, "Kairos Conseil")
    assert (task["done"], task["done_on"], task["overdue"], task["lead_id__label"]) == (True, _day(-6), False,
                                                                                      "Librairie Passages")
    assert email["opportunity_id__label"] == f"Rapport annuel {year}"

    # le CRM de démonstration ne crée ni client ni devis : il désigne ceux des Ventes
    names = [r["name"] for r in db.fetch_all("SELECT name FROM clients")]
    assert not set(names) & set(leads)
    titles = {r["title"] for r in db.fetch_all("SELECT title FROM invoices WHERE kind = 'quote'")}
    assert not titles & set(opportunities)

    kpis = {k["key"]: k for k in client.get("/api/home").json()["kpis"]}
    assert (kpis["crm.pipeline"]["value"], kpis["crm.pipeline"]["count"]) == (5580, 4)
    assert kpis["crm.open_opportunities"]["value"] == 4
    assert kpis["crm.activities_due"]["value"] == 2 and kpis["crm.activities_due"]["alert"] is True
