# SPDX-License-Identifier: AGPL-3.0-or-later
"""Qualité : non-conformités (numérotation, contrôles, calculs, cycle de vie, verrouillage, suppression), actions
correctives et préventives (lignes mises à jour sur place, date de réalisation), plan d'actions (vue SQL, retard),
droits (lecture seule, clôture réservée à la gestion), modules RH, Achats, Ventes et Données techniques désactivés,
chiffres clés, « Mes vues », vue en colonnes, export et données de démonstration."""

import csv
import io
from datetime import timedelta

import pytest

from caffein import dashboard, db
from caffein.core import modules as registry
from caffein.utils import today

from .helpers import article_id, disable_module, login_as, make_member

BASE = "/api/data/quality"
NOT_NOW = "Cette action n'est pas possible dans l'état actuel de la fiche."
CLOSED = "Non-conformité clôturée : elle ne se modifie plus. Rouvrez-la pour la compléter."
CRUSHED, TINT, CUT = "Boîtes kraft écrasées à la livraison", "Erreur de teinte sur des cartes de visite", "Coupe décalée au massicot"


@pytest.fixture()
def restore_modules():
    yield
    registry.enable_all()


def _day(offset: int = 0) -> str:
    return (today() + timedelta(days=offset)).isoformat()


def _error(res, status: int = 400) -> str:
    assert res.status_code == status, res.text
    return res.json()["detail"]


def _post(client, data: dict, entity: str = "nonconformities") -> dict:
    res = client.post(f"{BASE}/{entity}", json=data)
    assert res.status_code == 201, res.text
    return res.json()


def _get(client, row: dict) -> dict:
    res = client.get(f"{BASE}/nonconformities/{row['id']}")
    assert res.status_code == 200, res.text
    return res.json()


def _put(client, row: dict, data: dict) -> dict:
    res = client.put(f"{BASE}/nonconformities/{row['id']}", json=data)
    assert res.status_code == 200, res.text
    return res.json()


def _act(client, row: dict, action: str, payload: dict | None = None):
    return client.post(f"{BASE}/nonconformities/{row['id']}/actions/{action}", json=payload or {})


def _nc(client, title: str = "Rayures sur des kakémonos", **extra) -> dict:
    return _post(client, {"title": title, **extra})


def _employee(name: str) -> int:
    return db.fetch_one("SELECT id FROM hr_employees WHERE full_name = ?", (name,))["id"]


def _supplier(name: str) -> int:
    return db.fetch_one("SELECT id FROM purchases_suppliers WHERE name = ?", (name,))["id"]


def _client(name: str) -> int:
    return db.fetch_one("SELECT id FROM clients WHERE name = ?", (name,))["id"]


def _in_action(client, **extra) -> dict:
    """Une non-conformité dont les actions sont engagées : une corrective et une préventive, à faire."""
    nc = _nc(client, root_cause="Bâche mal protégée pendant le transport.", actions=[
        {"kind": "corrective", "description": "Réimprimer les kakémonos", "due_date": _day(3)},
        {"kind": "preventive", "description": "Emballer chaque kakémono dans un tube", "due_date": _day(10)},
    ], **extra)
    assert _act(client, nc, "plan").status_code == 200
    return _get(client, nc)


def _all_done(row: dict) -> list[dict]:
    return [{**line, "done": True} for line in row["actions"]]


def _plan_rows(client, **params) -> list[dict]:
    res = client.get(f"{BASE}/action_plan", params={"size": 200, **params})
    assert res.status_code == 200, res.text
    return res.json()["rows"]


# ═════════════════════════════════════════════════════════════════════════
# Déclaration
# ═════════════════════════════════════════════════════════════════════════
def test_meta_describes_the_module(client):
    meta = client.get("/api/meta").json()
    module = next(m for m in meta["modules"] if m["key"] == "quality")
    assert module["slug"] == "qualite" and module["label"] == ["Qualité", "Quality"] and module["icon"] == "BadgeCheck"
    assert [(p["slug"], p["entity"]) for p in module["pages"]] == [("non-conformites", "quality.nonconformities"),
                                                                   ("plan-actions", "quality.action_plan")]
    assert registry.get("quality").depends == () and registry.get("quality").order == 80
    ncs = meta["entities"]["quality.nonconformities"]
    assert ncs["label"] == ["Non-conformité", "Non-conformity"] and ncs["plural"] == ["Non-conformités", "Non-conformities"]
    assert ncs["title"] == "title" and ncs["board"] == "status" and not ncs["readonly"]
    assert [(a["key"], a["level"]) for a in ncs["actions"]] == [("analyse", 2), ("plan", 2), ("close", 3), ("reopen", 3)]
    assert [a["key"] for a in ncs["actions"] if a["confirm"]] == ["close", "reopen"]
    fields = {f["name"]: f for f in ncs["fields"]}
    assert fields["code"]["prefix"] == "NC" and fields["code"]["readonly"] and fields["code"]["search"]
    assert fields["title"]["required"] and fields["title"]["search"] and fields["title"]["list"]
    assert fields["detected_on"]["default"] == _day() and fields["detected_on"]["type"] == "date"
    assert [c["value"] for c in fields["origin"]["choices"]] == ["customer", "supplier", "internal", "audit"]
    assert fields["origin"]["choices"][0]["label"] == ["Réclamation client", "Customer complaint"]
    assert [(c["value"], c["tone"]) for c in fields["severity"]["choices"]] == [("minor", "outline"), ("major", "warn"),
                                                                              ("critical", "bad")]
    assert [(c["value"], c["label"][0], c["tone"]) for c in fields["status"]["choices"]] == [
        ("open", "Ouverte", "bad"), ("analysis", "En analyse", "warn"), ("action", "Actions en cours", "info"),
        ("closed", "Clôturée", "good")]
    assert fields["status"]["readonly"] and fields["status"]["default"] == "open" and fields["closed_on"]["readonly"]
    assert all(fields[name]["filter"] for name in ("origin", "severity", "status"))
    assert (fields["article_id"]["ref"], fields["supplier_id"]["ref"], fields["client_id"]["ref"]) == (
        "technical.articles", "purchases.suppliers", "sales.clients")
    assert fields["cost"]["type"] == "money" and fields["cost"]["min"] == 0
    assert fields["cost"]["label"] == ["Coût de la non-qualité", "Cost of poor quality"]
    assert fields["root_cause"]["label"][0] == "Cause racine" and fields["quantity_affected"]["min"] == 0
    assert fields["actions_open"]["computed"] and fields["age_days"]["computed"]
    assert [name for name, f in fields.items() if f["list"]] == ["code", "title", "detected_on", "origin", "severity",
                                                                 "status", "cost", "actions_open", "age_days"]
    [lines] = ncs["children"]
    assert lines["key"] == "actions" and lines["writable"]
    line_fields = {f["name"]: f for f in lines["fields"]}
    assert list(line_fields) == ["kind", "description", "owner_id", "due_date", "done", "done_on"]
    assert [c["value"] for c in line_fields["kind"]["choices"]] == ["corrective", "preventive"]
    assert line_fields["description"]["required"] and line_fields["owner_id"]["ref"] == "hr.employees"
    assert line_fields["done"]["default"] is False and not line_fields["done_on"]["readonly"]

    plan = meta["entities"]["quality.action_plan"]
    assert plan["readonly"] and not (plan["can_create"] or plan["can_edit"] or plan["can_delete"])
    assert plan["plural"] == ["Plan d'actions", "Action plan"] and plan["title"] == "description"
    plan_fields = {f["name"]: f for f in plan["fields"]}
    assert [name for name, f in plan_fields.items() if f["list"]] == [
        "description", "nonconformity_code", "nonconformity_title", "kind", "owner_id", "due_date", "done", "overdue"]
    assert plan_fields["overdue"]["computed"] and plan_fields["done"]["filter"] and plan_fields["kind"]["filter"]


# ═════════════════════════════════════════════════════════════════════════
# Saisie : numérotation, valeurs par défaut, contrôles
# ═════════════════════════════════════════════════════════════════════════
def test_numbering_defaults_and_validation(client):
    count = db.fetch_one("SELECT COUNT(*) AS n FROM quality_nonconformities")["n"]
    nc = _nc(client, code="PIRATE", status="closed", closed_on=_day(), actions_open=9, cost="12,5")
    assert nc["code"] == f"NC-{today().year}-{count + 1:04d}"
    assert (nc["status"], nc["closed_on"], nc["detected_on"], nc["origin"], nc["severity"]) == (
        "open", None, _day(), "internal", "minor")
    assert (nc["cost"], nc["actions_open"], nc["age_days"], nc["actions"]) == (12.5, 0, 0, [])
    assert nc["_actions"] == ["analyse", "plan"] and nc["_locked"] is None and nc["_deletable"] is True
    assert _nc(client, "Second défaut")["code"] == f"NC-{today().year}-{count + 2:04d}"
    # le numéro attribué ne change plus
    assert _put(client, nc, {"code": "", "title": "Rayures profondes"})["code"] == nc["code"]

    cases = (
        ({}, "Intitulé : obligatoire."),
        ({"title": "  "}, "Intitulé : obligatoire."),
        ({"title": "X" * 161}, "Intitulé : 160 caractères au plus."),
        ({"title": "X", "detected_on": None}, "Détectée le : obligatoire."),
        ({"title": "X", "detected_on": "31/02/2026"}, "Détectée le : date invalide."),
        ({"title": "X", "detected_on": _day(1)}, "Détectée le : la date ne peut pas être dans le futur."),
        ({"title": "X", "origin": "rumour"}, "Origine : valeur non proposée."),
        ({"title": "X", "severity": "fatal"}, "Gravité : valeur non proposée."),
        ({"title": "X", "severity": ""}, "Gravité : obligatoire."),
        ({"title": "X", "cost": -1}, "Coût de la non-qualité : 0 au minimum."),
        ({"title": "X", "cost": "cher"}, "Coût de la non-qualité : nombre attendu."),
        ({"title": "X", "quantity_affected": -2}, "Quantité concernée : 0 au minimum."),
        ({"title": "X", "article_id": 999999}, "Article : fiche introuvable."),
        ({"title": "X", "supplier_id": 999999}, "Fournisseur : fiche introuvable."),
        ({"title": "X", "client_id": 10**20}, "Client : nombre hors limites."),
        ({"title": "X", "actions": [{"kind": "corrective"}]}, "Actions, ligne 1 — Action : obligatoire."),
        ({"title": "X", "actions": [{"description": "Trier", "kind": "curative"}]},
         "Actions, ligne 1 — Type : valeur non proposée."),
        ({"title": "X", "actions": [{"description": "Trier", "owner_id": 999999}]},
         "Actions, ligne 1 — Responsable : fiche introuvable."),
        ({"title": "X", "actions": [{"description": "Trier"}, {"description": "Relancer", "done": True, "done_on": _day(1)}]},
         "Actions, ligne 2 — Faite le : la date ne peut pas être dans le futur."),
        ({"title": "X", "actions": "aucune"}, "Actions : liste attendue."),
    )
    for data, message in cases:
        assert _error(client.post(f"{BASE}/nonconformities", json=data)) == message, data

    # références des autres modules, avec leurs libellés ; recherche et filtres
    box, emballages = article_id("Boîte cadeau kraft 22×16 cm"), _supplier("Emballages du Rhône")
    linked = _nc(client, "Boîtes déchirées", origin="supplier", severity="major", article_id=box, supplier_id=emballages,
                 client_id=_client("Maison Verde"), quantity_affected="4,5", detected_on=_day(-3))
    assert (linked["article_id__label"], linked["supplier_id__label"], linked["client_id__label"]) == (
        "Boîte cadeau kraft 22×16 cm", "Emballages du Rhône", "Maison Verde")
    assert linked["quantity_affected"] == 4.5 and linked["age_days"] == 3
    found = client.get(f"{BASE}/nonconformities", params={"q": linked["code"]}).json()["rows"]
    assert [r["id"] for r in found] == [linked["id"]]
    mine = client.get(f"{BASE}/nonconformities", params={"f_supplier_id": emballages, "f_severity": "major",
                                                         "size": 200}).json()["rows"]
    assert linked["id"] in [r["id"] for r in mine] and {r["severity"] for r in mine} == {"major"}
    options = client.get(f"{BASE}/nonconformities/options", params={"q": "déchirées"}).json()
    assert options == [{"id": linked["id"], "label": "Boîtes déchirées", "sublabel": linked["code"]}]


# ═════════════════════════════════════════════════════════════════════════
# Calculs : actions à faire, ancienneté (fiche, liste, aperçu)
# ═════════════════════════════════════════════════════════════════════════
def test_computed_figures(client):
    nc = _nc(client, detected_on=_day(-12), actions=[
        {"description": "Trier le lot", "done": True},
        {"description": "Réimprimer", "kind": "corrective"},
        {"description": "Former l'équipe", "kind": "preventive", "due_date": _day(5)},
    ])
    assert (nc["actions_open"], nc["age_days"]) == (2, 12)
    listed = next(r for r in client.get(f"{BASE}/nonconformities", params={"size": 200}).json()["rows"]
                  if r["id"] == nc["id"])
    assert (listed["actions_open"], listed["age_days"]) == (2, 12)  # requête groupée : les mêmes chiffres
    assert "actions" not in listed

    # aperçu pendant la saisie : calculé par le serveur avec les valeurs et les lignes saisies, sans rien enregistrer
    preview = client.post(f"{BASE}/nonconformities/preview", params={"id": nc["id"]},
                          json={"detected_on": _day(-30), "actions": [{"description": "a"}, {"description": "b", "done": True}]})
    assert preview.status_code == 200 and preview.json()["computed"] == {"actions_open": 1, "age_days": 30}
    assert _get(client, nc)["age_days"] == 12
    assert client.post(f"{BASE}/nonconformities/preview", json={}).json()["computed"] == {"actions_open": 0, "age_days": None}
    invalid = client.post(f"{BASE}/nonconformities/preview", json={"detected_on": "hier", "actions": "x"}).json()
    assert invalid["computed"] == {"actions_open": 0, "age_days": None}

    # clôturée : l'ancienneté s'arrête à la date de clôture
    done = _in_action(client, detected_on=_day(-40))
    _put(client, done, {"actions": _all_done(done)})
    _act(client, done, "close", {"date": _day(-15)})
    closed = _get(client, done)
    assert (closed["closed_on"], closed["age_days"], closed["actions_open"]) == (_day(-15), 25, 0)


# ═════════════════════════════════════════════════════════════════════════
# Cycle de vie : analyse, actions, clôture, réouverture
# ═════════════════════════════════════════════════════════════════════════
def test_workflow_and_forbidden_transitions(client):
    nc = _nc(client, detected_on=_day(-5))
    assert _error(_act(client, nc, "close"), 409) == NOT_NOW
    assert _error(_act(client, nc, "reopen"), 409) == NOT_NOW
    res = _act(client, nc, "analyse")
    assert res.status_code == 200 and res.json()["message"] == f"Non-conformité {nc['code']} en analyse."
    row = res.json()["row"]
    assert row["status"] == "analysis" and row["_actions"] == ["plan"]
    assert _error(_act(client, nc, "analyse"), 409) == NOT_NOW

    # engager les actions : il faut la cause racine et au moins une action
    assert _error(_act(client, nc, "plan")) == "Cause racine : renseignez-la avant d'engager les actions."
    _put(client, nc, {"root_cause": "  "})
    assert _error(_act(client, nc, "plan")) == "Cause racine : renseignez-la avant d'engager les actions."
    _put(client, nc, {"root_cause": "Bâche mal protégée pendant le transport."})
    assert _error(_act(client, nc, "plan")) == \
        "Actions : ajoutez au moins une action corrective ou préventive avant de les engager."
    _put(client, nc, {"actions": [{"description": "Réimprimer les kakémonos", "due_date": _day(2)}]})
    res = _act(client, nc, "plan")
    assert res.json()["message"] == f"Non-conformité {nc['code']} : actions engagées."
    row = res.json()["row"]
    assert row["status"] == "action" and row["_actions"] == ["close"] and row["_locked"] is None
    assert _error(_act(client, nc, "plan"), 409) == NOT_NOW
    assert _error(_act(client, nc, "analyse"), 409) == NOT_NOW

    # actions en cours : la cause et au moins une action restent ; la fiche se complète
    assert _error(client.put(f"{BASE}/nonconformities/{nc['id']}", json={"root_cause": ""})) == \
        "Cause racine : elle reste obligatoire tant que les actions sont en cours."
    assert _error(client.put(f"{BASE}/nonconformities/{nc['id']}", json={"actions": []})) == \
        "Actions : gardez au moins une action tant que les actions sont en cours."
    row = _put(client, nc, {"actions": [*row["actions"], {"kind": "preventive", "description": "Emballer dans un tube"}]})
    assert row["actions_open"] == 2

    # clôture : toutes les actions faites
    assert _error(_act(client, nc, "close")) == ("Actions : 2 action(s) pas encore faite(s) ; la non-conformité se "
                                                "clôture une fois toutes ses actions faites.")
    _put(client, nc, {"actions": [{**row["actions"][0], "done": True}, row["actions"][1]]})
    assert "1 action(s) pas encore faite(s)" in _error(_act(client, nc, "close"))
    row = _put(client, nc, {"actions": _all_done(_get(client, nc))})
    assert row["actions_open"] == 0
    for date, message in ((_day(1), "Clôturée le : la date ne peut pas être dans le futur."),
                          (_day(-6), "Clôturée le : elle ne peut pas précéder la date de détection."),
                          ("le 3 mars", "Clôturée le : date invalide.")):
        assert _error(_act(client, nc, "close", {"date": date})) == message
    res = _act(client, nc, "close")
    assert res.json()["message"] == f"Non-conformité {nc['code']} clôturée."
    row = res.json()["row"]
    assert (row["status"], row["closed_on"], row["_locked"], row["_actions"], row["_deletable"]) == (
        "closed", _day(), CLOSED, ["reopen"], False)
    assert _error(_act(client, nc, "close"), 409) == NOT_NOW
    assert _error(_act(client, nc, "plan"), 409) == NOT_NOW

    # clôturée : verrouillée, ni modifiable ni supprimable
    assert _error(client.put(f"{BASE}/nonconformities/{nc['id']}", json={"title": "Autre"}), 409) == CLOSED
    assert _error(client.delete(f"{BASE}/nonconformities/{nc['id']}"), 409) == \
        "Une non-conformité clôturée ne se supprime pas : elle fait partie de l'historique qualité."

    # réouverture : de nouveau en cours, date de clôture effacée, modifiable
    res = _act(client, nc, "reopen")
    assert res.json()["message"] == f"Non-conformité {nc['code']} rouverte : ses actions sont de nouveau en cours."
    row = res.json()["row"]
    assert (row["status"], row["closed_on"], row["_locked"], row["_actions"]) == ("action", None, None, ["close"])
    assert _error(_act(client, nc, "reopen"), 409) == NOT_NOW
    assert _put(client, nc, {"description": "Complété après réouverture."})["description"] == "Complété après réouverture."

    # une non-conformité ouverte s'engage directement, sans passer par l'analyse
    direct = _in_action(client)
    assert direct["status"] == "action" and direct["actions_open"] == 2


def test_status_is_only_changed_by_the_buttons(client):
    nc = _nc(client)
    row = _put(client, nc, {"status": "closed", "closed_on": _day(), "title": "Rayures"})
    assert (row["status"], row["closed_on"], row["title"]) == ("open", None, "Rayures")
    meta = {f["name"]: f for f in client.get("/api/meta").json()["entities"]["quality.nonconformities"]["fields"]}
    assert meta["status"]["readonly"] and meta["closed_on"]["readonly"]


def test_simultaneous_actions_leave_one_change(client):
    """Deux clics sur le même bouton (deux personnes) : le second voit la fiche déjà modifiée."""
    from caffein.core.errors import Conflict
    from caffein.modules.quality.entities import NONCONFORMITIES

    nc = _nc(client)
    stale = _get(client, nc)
    actions = {a.key: a for a in NONCONFORMITIES.actions}
    actions["analyse"].run(stale, {}, {})
    with pytest.raises(Conflict):
        actions["analyse"].run(stale, {}, {})
    assert _get(client, nc)["status"] == "analysis"


# ═════════════════════════════════════════════════════════════════════════
# Actions correctives et préventives
# ═════════════════════════════════════════════════════════════════════════
def test_action_lines_are_updated_in_place(client):
    hugo, lea = _employee("Hugo Martin"), _employee("Léa Bernard")
    nc = _nc(client, actions=[
        {"description": "Trier le lot", "owner_id": hugo, "due_date": _day(-2)},
        {"description": "Prévenir le client", "owner_id": lea, "done": True},
    ])
    first, second = nc["actions"]
    assert (first["owner_id__label"], first["done"], first["done_on"], first["kind"]) == ("Hugo Martin", False, None,
                                                                                         "corrective")
    assert (second["done"], second["done_on"]) == (True, _day())  # cochée sans date : la date du jour
    # une ligne envoyée avec son id est mise à jour ; une ligne sans id est nouvelle ; une ligne absente est supprimée
    row = _put(client, nc, {"actions": [
        {"id": first["id"], "done": True, "done_on": _day(-1)},
        {"description": "Contrôler le lot suivant", "kind": "preventive", "due_date": _day(14)},
    ]})
    kept, added = row["actions"]
    assert kept["id"] == first["id"] and (kept["description"], kept["owner_id"], kept["due_date"]) == (
        "Trier le lot", hugo, _day(-2))
    assert (kept["done"], kept["done_on"]) == (True, _day(-1))
    assert added["id"] not in (first["id"], second["id"]) and added["kind"] == "preventive"
    assert db.fetch_one("SELECT COUNT(*) AS n FROM quality_actions WHERE id = ?", (second["id"],))["n"] == 0
    # décochée : la date de réalisation est effacée
    row = _put(client, nc, {"actions": [{"id": kept["id"], "done": False}, {"id": added["id"]}]})
    assert (row["actions"][0]["done"], row["actions"][0]["done_on"]) == (False, None)
    # une case envoyée vide garde sa valeur
    _put(client, nc, {"actions": [{"id": kept["id"], "done": True}, {"id": added["id"]}]})
    row = _put(client, nc, {"actions": [{"id": kept["id"], "done": None}, {"id": added["id"]}]})
    assert row["actions"][0]["done"] is True and row["actions"][0]["done_on"] == _day()


def test_action_plan_view(client):
    hugo = _employee("Hugo Martin")
    nc = _nc(client, "Kakémonos rayés", actions=[
        {"description": "Réimprimer", "due_date": _day(-1), "owner_id": hugo},
        {"description": "Appeler le client", "due_date": _day()},
        {"description": "Changer l'emballage", "kind": "preventive", "due_date": _day(-3), "done": True},
        {"description": "Mettre à jour la procédure", "kind": "preventive"},
    ])
    rows = {r["description"]: r for r in _plan_rows(client, f_nonconformity_id=nc["id"])}
    assert set(rows) == {"Réimprimer", "Appeler le client", "Changer l'emballage", "Mettre à jour la procédure"}
    late = rows["Réimprimer"]
    assert late["id"] == nc["actions"][0]["id"]  # l'identifiant de la ligne
    assert (late["nonconformity_code"], late["nonconformity_title"], late["nonconformity_status"]) == (
        nc["code"], "Kakémonos rayés", "open")
    assert (late["kind"], late["owner_id__label"], late["due_date"], late["done"]) == ("corrective", "Hugo Martin",
                                                                                     _day(-1), False)
    # en retard : pas faite et échéance passée ; aujourd'hui n'est pas en retard ; faite, jamais en retard
    assert {d: r["overdue"] for d, r in rows.items()} == {"Réimprimer": True, "Appeler le client": False,
                                                          "Changer l'emballage": False, "Mettre à jour la procédure": False}
    assert rows["Changer l'emballage"]["done_on"] == _day()
    # à faire d'abord, échéances les plus proches en tête, sans échéance à la fin
    assert [r["description"] for r in _plan_rows(client, f_nonconformity_id=nc["id"])] == [
        "Réimprimer", "Appeler le client", "Mettre à jour la procédure", "Changer l'emballage"]
    pending = _plan_rows(client, f_done=0, f_kind="preventive", q=nc["code"])
    assert [r["description"] for r in pending] == ["Mettre à jour la procédure"]
    record = client.get(f"{BASE}/action_plan/{late['id']}").json()
    assert record["nonconformity_id__label"] == "Kakémonos rayés" and record["overdue"] is True
    assert record["_deletable"] is False and record["_actions"] == []
    # consultation seulement : les actions se modifient dans la fiche de leur non-conformité
    assert client.post(f"{BASE}/action_plan", json={"description": "x"}).status_code == 409
    assert client.put(f"{BASE}/action_plan/{late['id']}", json={"done": True}).status_code == 409
    assert client.delete(f"{BASE}/action_plan/{late['id']}").status_code == 409
    # une action faite dans la fiche quitte le retard ; supprimer la non-conformité retire ses actions du plan
    lines = [{**line, "done": line["id"] == late["id"] or line["done"]} for line in _get(client, nc)["actions"]]
    _put(client, nc, {"actions": lines})
    assert next(r for r in _plan_rows(client, f_nonconformity_id=nc["id"]) if r["id"] == late["id"])["overdue"] is False
    assert client.delete(f"{BASE}/nonconformities/{nc['id']}").status_code == 204
    assert _plan_rows(client, f_nonconformity_id=nc["id"]) == []


# ═════════════════════════════════════════════════════════════════════════
# Suppression
# ═════════════════════════════════════════════════════════════════════════
def test_deletion_rules_and_protected_references(client):
    lumen = client.post("/api/data/purchases/suppliers", json={"name": "Encres Lumen"}).json()
    owner = client.post("/api/data/hr/employees", json={"first_name": "Jeanne", "last_name": "Qualité"}).json()
    nc = _nc(client, supplier_id=lumen["id"], actions=[{"description": "Analyser l'encre", "owner_id": owner["id"]}])
    # le fournisseur et le salarié désignés par la non-conformité ne se suppriment pas
    assert _error(client.delete(f"/api/data/purchases/suppliers/{lumen['id']}"), 409) == \
        "Suppression impossible : cette fiche est utilisée ailleurs (non-conformités : 1)."
    assert "non-conformités : 1" in _error(client.delete(f"/api/data/hr/employees/{owner['id']}"), 409)
    # en cours (pas clôturée) : la non-conformité se supprime, avec ses actions ; ensuite plus rien ne les retient
    _act(client, nc, "analyse")
    assert _get(client, nc)["_deletable"] is True
    assert client.delete(f"{BASE}/nonconformities/{nc['id']}").status_code == 204
    assert db.fetch_one("SELECT COUNT(*) AS n FROM quality_actions WHERE nonconformity_id = ?", (nc["id"],))["n"] == 0
    assert client.delete(f"/api/data/purchases/suppliers/{lumen['id']}").status_code == 204
    assert client.delete(f"/api/data/hr/employees/{owner['id']}").status_code == 204


# ═════════════════════════════════════════════════════════════════════════
# Droits
# ═════════════════════════════════════════════════════════════════════════
def test_readonly_role_cannot_write(client):
    nc = _in_action(client)
    make_member("lecture-qualite@test.local", "readonly")
    reader = login_as("lecture-qualite@test.local")
    assert reader.get(f"{BASE}/nonconformities").status_code == 200
    assert reader.get(f"{BASE}/action_plan").status_code == 200
    assert reader.get(f"{BASE}/nonconformities/{nc['id']}").json()["_actions"] == []
    assert reader.post(f"{BASE}/nonconformities", json={"title": "Lecture"}).status_code == 403
    assert reader.put(f"{BASE}/nonconformities/{nc['id']}", json={"title": "x"}).status_code == 403
    assert reader.post(f"{BASE}/nonconformities/preview", json={}).status_code == 403
    assert reader.delete(f"{BASE}/nonconformities/{nc['id']}").status_code == 403
    for action in ("analyse", "plan", "close", "reopen"):
        assert reader.post(f"{BASE}/nonconformities/{nc['id']}/actions/{action}").status_code == 403
    meta = reader.get("/api/meta").json()["entities"]["quality.nonconformities"]
    assert not meta["can_create"] and not meta["can_edit"] and not meta["can_delete"]
    home = reader.get("/api/home").json()
    assert "quality.open_nonconformities" in {k["key"] for k in home["kpis"]}
    assert "quality.new_nonconformity" not in {s["key"] for s in home["shortcuts"]}  # raccourci : niveau écriture
    assert _get(client, nc)["status"] == "action"


def test_close_and_reopen_need_the_manage_level(client):
    make_member("equipe-qualite@test.local", "team")  # écriture sur tous les modules
    member = login_as("equipe-qualite@test.local")
    created = member.post(f"{BASE}/nonconformities", json={
        "title": "Étiquettes décollées", "root_cause": "Colle inadaptée au froid.",
        "actions": [{"description": "Changer de colle", "done": True}]})
    assert created.status_code == 201
    nc = created.json()
    assert nc["_actions"] == ["analyse", "plan"] and nc["_deletable"] is False  # suppression : gestion
    assert member.post(f"{BASE}/nonconformities/{nc['id']}/actions/analyse").status_code == 200
    planned = member.post(f"{BASE}/nonconformities/{nc['id']}/actions/plan")
    assert planned.status_code == 200 and planned.json()["row"]["_actions"] == []  # la clôture ne lui est pas proposée
    res = member.post(f"{BASE}/nonconformities/{nc['id']}/actions/close")
    assert res.status_code == 403 and res.json()["detail"] == "Droits insuffisants pour cette action."
    assert member.delete(f"{BASE}/nonconformities/{nc['id']}").status_code == 403
    assert _act(client, nc, "close").status_code == 200  # un gestionnaire clôture
    assert member.post(f"{BASE}/nonconformities/{nc['id']}/actions/reopen").status_code == 403
    assert _get(client, nc)["status"] == "closed"
    # avec le niveau gestion sur la Qualité, le membre clôture et rouvre lui-même
    manager = make_member("responsable-qualite@test.local", "team", {"quality": "manage"})
    assert manager["role"] == "member"
    boss = login_as("responsable-qualite@test.local")
    assert boss.post(f"{BASE}/nonconformities/{nc['id']}/actions/reopen").status_code == 200
    assert boss.post(f"{BASE}/nonconformities/{nc['id']}/actions/close").status_code == 200


# ═════════════════════════════════════════════════════════════════════════
# Modules désactivés
# ═════════════════════════════════════════════════════════════════════════
def test_disabled_quality_disappears(client, restore_modules):
    nc = _nc(client)
    disable_module(client, "quality")
    assert client.get(f"{BASE}/nonconformities").status_code == 404
    assert client.get(f"{BASE}/nonconformities/{nc['id']}").status_code == 404
    assert client.get(f"{BASE}/action_plan").status_code == 404
    assert client.post(f"{BASE}/nonconformities", json={"title": "X"}).status_code == 404
    assert client.post(f"{BASE}/nonconformities/{nc['id']}/actions/analyse").status_code == 404
    meta = client.get("/api/meta").json()
    assert "quality" not in [m["key"] for m in meta["modules"]] and "quality.nonconformities" not in meta["entities"]
    home = client.get("/api/home").json()
    assert not [k for k in home["kpis"] if k["module"] == "quality"]
    assert not [s for s in home["shortcuts"] if s["module"] == "quality"]
    # ses données restent, et protègent toujours les fiches qu'elles désignent
    res = client.delete(f"/api/data/hr/employees/{_employee('Hugo Martin')}")
    assert res.status_code == 409 and "non-conformités" in res.json()["detail"]
    assert client.put("/api/settings/modules/quality", json={"enabled": True}).status_code == 200
    assert _get(client, nc)["code"] == nc["code"]


def test_quality_works_without_the_other_modules(client, restore_modules):
    hugo = _employee("Hugo Martin")
    box = article_id("Boîte cadeau kraft 22×16 cm")
    nc = _nc(client, article_id=box, supplier_id=_supplier("Emballages du Rhône"), client_id=_client("Atelier Nova"),
             actions=[{"description": "Trier le lot", "owner_id": hugo}])
    for key in ("hr", "purchases", "sales", "technical"):  # la Logistique et la Production, qui en dépendent, d'abord
        disable_module(client, key)
    meta = client.get("/api/meta").json()["entities"]
    fields = {f["name"] for f in meta["quality.nonconformities"]["fields"]}
    assert not {"article_id", "supplier_id", "client_id"} & fields and "title" in fields
    assert "owner_id" not in {f["name"] for f in meta["quality.nonconformities"]["children"][0]["fields"]}
    assert "owner_id" not in {f["name"] for f in meta["quality.action_plan"]["fields"]}
    row = _get(client, nc)
    assert "article_id" not in row and "owner_id" not in row["actions"][0]
    # la fiche se complète et suit son cycle : la ligne envoyée avec son id garde son responsable
    row = _put(client, nc, {"root_cause": "Calage insuffisant.", "actions": [
        {"id": row["actions"][0]["id"], "description": "Trier et isoler le lot", "done": True},
        {"description": "Contrôler à réception", "kind": "preventive"}]})
    assert _act(client, nc, "plan").status_code == 200
    created = _nc(client, "Défaut sans référence", actions=[{"description": "Analyser", "owner_id": hugo}])
    assert created["actions"][0]["description"] == "Analyser"
    assert client.get(f"{BASE}/action_plan", params={"q": nc["code"]}).json()["total"] == 2
    assert client.get(f"{BASE}/nonconformities/export").status_code == 200
    assert {k["key"] for k in client.get("/api/home").json()["kpis"]} >= {"quality.open_nonconformities",
                                                                          "quality.overdue_actions", "quality.cost_year"}
    registry.enable_all()
    row = _get(client, nc)
    assert (row["article_id"], row["supplier_id__label"], row["client_id__label"]) == (box, "Emballages du Rhône",
                                                                                       "Atelier Nova")
    assert row["actions"][0]["owner_id"] == hugo and row["actions"][0]["description"] == "Trier et isoler le lot"
    assert row["actions"][1]["owner_id"] is None
    # une référence vers un module désactivé n'est pas enregistrée
    assert _get(client, created)["actions"][0]["owner_id"] is None


# ═════════════════════════════════════════════════════════════════════════
# Chiffres clés, « Mes vues », vue en colonnes, export
# ═════════════════════════════════════════════════════════════════════════
def _kpis(client) -> dict:
    return {k["key"]: k for k in client.get("/api/home").json()["kpis"] if k["module"] == "quality"}


def test_home_kpis_follow_the_nonconformities(client):
    start = _kpis(client)
    assert set(start) == {"quality.open_nonconformities", "quality.overdue_actions", "quality.cost_year"}
    assert start["quality.open_nonconformities"]["path"] == "/qualite/non-conformites?view=board"
    assert start["quality.overdue_actions"]["path"] == "/qualite/plan-actions?f_done=0&sort=due_date"
    assert start["quality.cost_year"]["unit"] == "money" and start["quality.cost_year"]["path"] == "/qualite/non-conformites"
    shortcut = next(s for s in client.get("/api/home").json()["shortcuts"] if s["key"] == "quality.new_nonconformity")
    assert shortcut["path"] == "/qualite/non-conformites?new=1"
    assert shortcut["label"] == ["Déclarer une non-conformité", "Report a non-conformity"]

    # rien d'ouvert : aucune alerte
    db.execute("UPDATE quality_nonconformities SET status = 'closed'")
    db.execute("UPDATE quality_actions SET done = 1")
    calm = _kpis(client)
    assert calm["quality.open_nonconformities"]["value"] == 0 and calm["quality.open_nonconformities"]["alert"] is False
    assert calm["quality.overdue_actions"]["value"] == 0 and calm["quality.overdue_actions"]["alert"] is False

    minor = _nc(client, cost=100.005, detected_on=_day(-1), actions=[
        {"description": "En retard", "due_date": _day(-1)}, {"description": "Échéance aujourd'hui", "due_date": _day()},
        {"description": "Faite en retard", "due_date": _day(-5), "done": True}, {"description": "Sans échéance"}])
    _nc(client, "Constat de l'audit de l'an dernier", origin="audit", cost=999, detected_on=f"{today().year - 1}-12-31")
    now = _kpis(client)
    assert (now["quality.open_nonconformities"]["value"], now["quality.open_nonconformities"]["count"]) == (2, 0)
    assert now["quality.open_nonconformities"]["alert"] is False  # aucune critique
    assert (now["quality.overdue_actions"]["value"], now["quality.overdue_actions"]["alert"]) == (1, True)
    year = start["quality.cost_year"]
    assert now["quality.cost_year"]["value"] == round(year["value"] + 100.01, 2)  # au centime, la moitié vers le haut
    assert now["quality.cost_year"]["count"] == year["count"] + 1  # l'audit de l'an dernier ne compte pas

    critical = _nc(client, "Lame cassée", severity="critical")
    alert = _kpis(client)["quality.open_nonconformities"]
    assert (alert["value"], alert["count"], alert["alert"]) == (3, 1, True)
    # chaque chiffre clé correspond à la liste qu'il ouvre
    _put(client, critical, {"root_cause": "Usure.", "actions": [{"description": "Changer la lame", "done": True}]})
    _act(client, critical, "plan")
    _act(client, critical, "close")
    end = _kpis(client)
    assert (end["quality.open_nonconformities"]["value"], end["quality.open_nonconformities"]["count"]) == (2, 0)
    late = [r for r in _plan_rows(client, f_done=0) if r["overdue"]]
    assert end["quality.overdue_actions"]["value"] == len(late) == 1 and late[0]["nonconformity_code"] == minor["code"]


def test_kpis_are_offered_in_my_views(client):
    """« Mes vues » reconnaît un chiffre clé quand la demande cite son libellé : chaque libellé nomme ce qu'il compte."""
    def widgets(text):
        return dashboard.compose_offline(text, {})["spec"]["widgets"]

    module = registry.get("quality")
    assert [k.key for k in module.kpis] == ["open_nonconformities", "overdue_actions", "cost_year"]
    for kpi in module.kpis:
        for label in kpi.label:
            assert [(w["source"], w["params"].get("metric")) for w in widgets(f"Montre-moi : {label.lower()}")] == [
                ("kpi", f"quality.{kpi.key}")], label
    for text in ("mes factures en retard", "le total en retard", "mes dépenses de l'année", "mes actions commerciales"):
        assert not [w for w in widgets(text) if w["params"].get("metric", "").startswith("quality.")], text
    res = client.post("/api/dashboards/compose", json={"text": "Montre-moi les non-conformités ouvertes"})
    [card] = [w for w in res.json()["view"]["widgets"] if w["source"] == "kpi"]
    opened = [r for r in client.get(f"{BASE}/nonconformities", params={"size": 200}).json()["rows"] if r["status"] != "closed"]
    assert card["params"]["metric"] == "quality.open_nonconformities" and card["data"]["value"] == len(opened)
    # sans accès à la Qualité, la demande ne montre pas ces chiffres
    make_member("sans-qualite@test.local", "sales")
    seller = login_as("sans-qualite@test.local")
    res = seller.post("/api/dashboards/compose", json={"text": "Montre-moi les non-conformités ouvertes"}).json()
    assert not [w for w in res["view"]["widgets"] if w["params"].get("metric", "").startswith("quality.")]


def test_board_counts_and_costs_by_status(client):
    before = {c["value"]: c for c in client.get(f"{BASE}/nonconformities/board").json()["columns"]}
    _nc(client, "Défaut A", cost=10.5)
    _nc(client, "Défaut B", cost=4)
    _in_action(client, cost=20)
    board = client.get(f"{BASE}/nonconformities/board").json()
    assert board["field"] == "status" and board["amount_field"] == "cost"
    columns = {c["value"]: c for c in board["columns"]}
    assert list(columns) == ["open", "analysis", "action", "closed"]
    assert columns["open"]["count"] == before["open"]["count"] + 2
    assert columns["open"]["amount"] == round(before["open"]["amount"] + 14.5, 2)
    assert columns["action"]["count"] == before["action"]["count"] + 1
    assert columns["action"]["amount"] == round(before["action"]["amount"] + 20, 2)
    assert columns["open"]["label"] == ["Ouverte", "Open"] and columns["open"]["tone"] == "bad"


def test_export_lists_the_nonconformities(client):
    nc = _nc(client, "Couleur hors tolérance", origin="customer", severity="major", cost="37,5", detected_on=_day(-2),
             actions=[{"description": "Réimprimer"}])
    res = client.get(f"{BASE}/nonconformities/export", params={"q": nc["code"]})
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    header, *rows = list(csv.reader(io.StringIO(res.text.lstrip("﻿")), delimiter=";"))
    [row] = rows
    cells = dict(zip(header, row, strict=True))
    assert (cells["Numéro"], cells["Intitulé"], cells["Origine"], cells["Gravité"], cells["Statut"]) == (
        nc["code"], "Couleur hors tolérance", "Réclamation client", "Majeure", "Ouverte")
    assert (cells["Coût de la non-qualité"], cells["Actions à faire"], cells["Ancienneté (jours)"]) == ("37,50", "1", "2")
    plan = client.get(f"{BASE}/action_plan/export", params={"q": nc["code"], "lang": "en"}).text.lstrip("﻿")
    header, row = list(csv.reader(io.StringIO(plan)))
    cells = dict(zip(header, row, strict=True))
    assert (cells["Action"], cells["Non-conformity"], cells["Done"], cells["Overdue"]) == ("Réimprimer", nc["code"],
                                                                                          "No", "No")


# ═════════════════════════════════════════════════════════════════════════
# Démonstration
# ═════════════════════════════════════════════════════════════════════════
def test_demo_data(client):
    rows = {r["title"]: r for r in client.get(f"{BASE}/nonconformities", params={"size": 200}).json()["rows"]}
    assert {CRUSHED, TINT, CUT} <= set(rows)
    crushed = _get(client, rows[CRUSHED])
    assert (crushed["origin"], crushed["severity"], crushed["status"]) == ("supplier", "major", "action")
    assert (crushed["article_id__label"], crushed["supplier_id__label"]) == ("Boîte cadeau kraft 22×16 cm",
                                                                             "Emballages du Rhône")
    assert (crushed["quantity_affected"], crushed["cost"], crushed["actions_open"]) == (12, 16.2, 1)
    assert crushed["root_cause"] and crushed["_actions"] == ["close"]
    corrective, preventive = crushed["actions"]
    assert (corrective["kind"], corrective["description"], corrective["done"]) == ("corrective",
                                                                                 "Retour au fournisseur et avoir", True)
    assert (preventive["kind"], preventive["description"], preventive["done"], preventive["due_date"]) == (
        "preventive", "Contrôle à réception des emballages", False, _day(7))
    assert preventive["owner_id__label"] == "Hugo Martin"

    tint = _get(client, rows[TINT])
    assert (tint["origin"], tint["severity"], tint["status"], tint["closed_on"]) == ("customer", "minor", "closed", _day(-20))
    assert (tint["client_id__label"], tint["cost"], tint["actions_open"], tint["_locked"]) == ("Atelier Nova", 45, 0, CLOSED)
    assert tint["age_days"] == 11 and all(line["done"] for line in tint["actions"])

    cut = rows[CUT]
    assert (cut["origin"], cut["severity"], cut["status"], cut["detected_on"], cut["age_days"]) == (
        "internal", "critical", "open", _day(-1), 1)
    plan = _plan_rows(client, q=crushed["code"])
    assert {r["description"] for r in plan} == {"Retour au fournisseur et avoir", "Contrôle à réception des emballages"}
    kpis = _kpis(client)
    assert kpis["quality.open_nonconformities"]["alert"] is True  # la coupe décalée est critique
