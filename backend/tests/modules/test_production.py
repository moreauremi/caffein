# SPDX-License-Identifier: AGPL-3.0-or-later
"""Production : ordres de fabrication (prévision en brouillon, lancement, fin avec mouvements de stock, annulation),
besoins et manques, coûts, charge des postes, droits, activation, chiffres clés et données de démonstration."""

import csv
import io
from datetime import timedelta

import pytest

from caffein import dashboard, db
from caffein.core import modules as registry
from caffein.core.errors import Conflict
from caffein.modules.production.entities import ORDERS
from caffein.modules.stock import services as stock
from caffein.modules.technical import services as technical
from caffein.utils import today

from .helpers import article_id, disable_module, login_as, make_member

BASE = "/api/data/production"
TECH = "/api/data/technical"
KIT, CARDS = "Kit papeterie de marque", "Jeu de cartes de visite (100 ex.)"
PAPER = "Papier couché 350 g, feuille SRA3"
FIGURES = ("material_cost", "labour_cost", "total_cost", "unit_cost", "shortages", "late")
NO_BOM = "Cet article n'a pas de nomenclature active : créez-la dans Données techniques."


@pytest.fixture()
def restore_modules():
    yield
    registry.enable_all()


def _day(offset: int = 0) -> str:
    return (today() + timedelta(days=offset)).isoformat()


def _post(client, path: str, data: dict) -> dict:
    res = client.post(path, json=data)
    assert res.status_code == 201, res.text
    return res.json()


def _product(client) -> dict:
    """Un coffret de prestige, fabriqué par deux (nomenclature pour 2 coffrets) : 3 cartons (10 % de pertes), un ruban
    et un calage, semi-fini fabriqué lui aussi (un demi-carton et 2 minutes de pliage). Gamme : dorure (réglage 30 min,
    3 min par coffret, 60 €/h, 7 h/jour) puis pliage (5 min par coffret, 36 €/h, capacité non renseignée)."""
    press = _post(client, f"{TECH}/workcenters", {"name": "Presse à dorer", "hourly_cost": 60, "capacity_hours": 7})
    folding = _post(client, f"{TECH}/workcenters", {"name": "Poste de pliage", "kind": "manual", "hourly_cost": 36})
    board = _post(client, f"{TECH}/articles", {"name": "Carton gris 2 mm", "kind": "raw", "unit": "feuille", "purchase_price": 0.8})
    ribbon = _post(client, f"{TECH}/articles", {"name": "Ruban satin doré", "kind": "raw", "unit": "m", "purchase_price": 1.3})
    wedge = _post(client, f"{TECH}/articles", {"name": "Calage carton", "kind": "semi"})
    box = _post(client, f"{TECH}/articles", {"name": "Coffret prestige", "kind": "finished", "sale_price": 49})
    _post(client, f"{TECH}/boms", {"article_id": wedge["id"], "lines": [{"article_id": board["id"], "quantity": 0.5}]})
    _post(client, f"{TECH}/routings", {"article_id": wedge["id"], "steps": [
        {"workcenter_id": folding["id"], "description": "Découpe du calage", "run_minutes": 2}]})
    bom = _post(client, f"{TECH}/boms", {"article_id": box["id"], "quantity": 2, "lines": [
        {"article_id": board["id"], "quantity": 3, "scrap_rate": 10}, {"article_id": ribbon["id"], "quantity": 1},
        {"article_id": wedge["id"], "quantity": 1}]})
    routing = _post(client, f"{TECH}/routings", {"article_id": box["id"], "steps": [
        {"workcenter_id": press["id"], "description": "Dorure à chaud", "setup_minutes": 30, "run_minutes": 3},
        {"workcenter_id": folding["id"], "description": "Pliage et assemblage", "run_minutes": 5}]})
    return {"press": press["id"], "folding": folding["id"], "board": board["id"], "ribbon": ribbon["id"],
            "wedge": wedge["id"], "box": box["id"], "bom": bom["id"], "routing": routing["id"]}


def _order(client, article: int, quantity: float, **extra) -> dict:
    return _post(client, f"{BASE}/orders", {"article_id": article, "quantity": quantity, **extra})


def _act(client, order: dict, action: str, **payload):
    return client.post(f"{BASE}/orders/{order['id']}/actions/{action}", json=payload)


def _run(client, order: dict, action: str) -> dict:
    res = _act(client, order, action)
    assert res.status_code == 200, res.text
    return res.json()


def _receive(client, article: int, quantity: float, warehouse: int | None = None) -> None:
    _post(client, "/api/data/stock/movements", {"kind": "receipt", "article_id": article, "quantity": quantity,
                                                "warehouse_id": warehouse})


def _moves(order: dict) -> list[tuple]:
    return [tuple(r.values()) for r in db.fetch_all(
        "SELECT kind, article_id, quantity, warehouse_id, date, reference FROM stock_movements WHERE source = ? ORDER BY id",
        (f"production.orders:{order['id']}",))]


def _stored(order: dict) -> tuple[list[tuple], list[tuple]]:
    components = db.fetch_all("SELECT position, article_id, quantity FROM production_order_components WHERE order_id = ? "
                              "ORDER BY position", (order["id"],))
    operations = db.fetch_all("SELECT position, workcenter_id, description, planned_minutes FROM production_order_operations "
                              "WHERE order_id = ? ORDER BY position", (order["id"],))
    return [tuple(r.values()) for r in components], [tuple(r.values()) for r in operations]


def _error(res, status: int = 400) -> str:
    assert res.status_code == status, res.text
    return res.json()["detail"]


def _listed(client, order: dict) -> dict:
    rows = client.get(f"{BASE}/orders", params={"size": 200}).json()["rows"]
    return next(r for r in rows if r["id"] == order["id"])


def _load(client) -> dict[str, dict]:
    return {r["workcenter_name"]: r for r in client.get(f"{BASE}/load", params={"size": 200}).json()["rows"]}


def _kpis(client) -> dict[str, dict]:
    return {k["key"]: k for k in client.get("/api/home").json()["kpis"]}


# ═════════════════════════════════════════════════════════════════════════
# Brouillon : numérotation, prévision d'après la nomenclature et la gamme
# ═════════════════════════════════════════════════════════════════════════
def test_draft_forecast_from_the_demo_bills(client):
    kit = article_id(KIT)
    count = db.fetch_one("SELECT COUNT(*) AS n FROM production_orders")["n"]
    order = _order(client, kit, 3, code="PIRATE", status="done", produced_quantity=3, completed_on=_day(), bom_id=1,
                   material_cost=1, shortages=9, components=[{"article_id": kit, "quantity": 1000}])
    assert order["code"] == f"OF-{today().year}-{count + 1:04d}" and order["status"] == "draft"
    assert (order["produced_quantity"], order["completed_on"], order["bom_id"]) == (None, None, None)
    assert order["planned_start"] == _day() and order["planned_end"] is None and order["warehouse_id"] is None
    assert order["article_id__label"] == KIT and order["_locked"] is None and set(order["_actions"]) == {"release", "cancel"}
    # besoins du kit standard, pertes comprises : 25 enveloppes × 3 × 1,02 ; 10 feuilles × 3 × 1,03
    assert [(c["article_id__label"], c["quantity"]) for c in order["components"]] == [
        (CARDS, 3), ("Enveloppe kraft C5", 76.5), (PAPER, 30.9), ("Boîte cadeau kraft 22×16 cm", 3),
        ("Papier de soie (feuille)", 12)]
    # temps : réglage + temps unitaire × 3, au coût horaire du poste (45, 30 et 32 €/h)
    assert [(o["workcenter_id__label"], o["description"], o["planned_minutes"], o["cost"]) for o in order["operations"]] == [
        ("Imprimante numérique", "Impression des en-têtes", 39, 29.25), ("Massicot", "Découpe", 17, 8.5),
        ("Atelier de façonnage", "Assemblage et emballage", 60, 32)]
    for line in order["components"]:
        assert line["available"] == stock.on_hand(line["article_id"])
        assert line["shortage"] == round(max(line["quantity"] - line["available"], 0), 6)
    assert order["shortages"] == sum(1 for line in order["components"] if line["shortage"] > 0)
    material = round(sum(c["quantity"] * technical.cost_price(c["article_id"]) for c in order["components"]), 2)
    assert (order["material_cost"], order["labour_cost"]) == (material, 69.75)
    assert order["total_cost"] == round(material + 69.75, 2) and order["unit_cost"] == round(order["total_cost"] / 3, 2)
    assert order["late"] is False
    # une prévision : rien n'est enregistré avec le brouillon
    assert _stored(order) == ([], [])
    # la liste calcule les mêmes chiffres (sans les lignes)
    listed = _listed(client, order)
    assert {k: listed[k] for k in FIGURES} == {k: order[k] for k in FIGURES} and "components" not in listed
    # l'aperçu d'une saisie calcule les mêmes chiffres, sans rien enregistrer
    preview = client.post(f"{BASE}/orders/preview", json={"article_id": kit, "quantity": 3}).json()
    assert preview["computed"] == {k: order[k] for k in FIGURES} and preview["children"] == {}
    # … et les lignes prévues, complètes, pour les afficher pendant la saisie
    assert [(c["article_id__label"], c["quantity"]) for c in preview["lines"]["components"]] == [
        (c["article_id__label"], c["quantity"]) for c in order["components"]]
    assert [o["planned_minutes"] for o in preview["lines"]["operations"]] == [39, 17, 60]
    six = client.post(f"{BASE}/orders/preview", json={"article_id": kit, "quantity": 6}).json()["lines"]
    assert [c["quantity"] for c in six["components"]] == [6, 153, 61.8, 6, 24]
    assert db.fetch_one("SELECT COUNT(*) AS n FROM production_orders")["n"] == count + 1
    # la prévision suit la quantité…
    edited = client.put(f"{BASE}/orders/{order['id']}", json={"quantity": 6, "code": "X"}).json()
    assert edited["code"] == order["code"]
    assert [c["quantity"] for c in edited["components"]] == [6, 153, 61.8, 6, 24]
    assert [o["planned_minutes"] for o in edited["operations"]] == [63, 29, 120]
    # … et l'article : 10 jeux de cartes, 5 feuilles × 10 × 1,04
    cards = client.put(f"{BASE}/orders/{order['id']}", json={"article_id": article_id(CARDS), "quantity": 10}).json()
    assert [(c["article_id__label"], c["quantity"]) for c in cards["components"]] == [(PAPER, 52)]
    assert [(o["workcenter_id__label"], o["planned_minutes"], o["cost"]) for o in cards["operations"]] == [
        ("Imprimante numérique", 50, 37.5), ("Massicot", 35, 17.5)]
    assert cards["labour_cost"] == 55 and _stored(cards) == ([], [])
    second = _order(client, kit, 1)
    assert second["code"] == f"OF-{today().year}-{count + 2:04d}"


def test_preview_tolerates_missing_and_invalid_values(client):
    empty = client.post(f"{BASE}/orders/preview", json={}).json()
    assert empty["computed"] == {"material_cost": None, "labour_cost": None, "total_cost": None, "unit_cost": None,
                                 "shortages": 0, "late": False}
    kit = article_id(KIT)
    for data in ({"article_id": kit}, {"article_id": kit, "quantity": "beaucoup"}, {"article_id": kit, "quantity": -4},
                 {"article_id": 999999, "quantity": 2}, {"article_id": 10**20, "quantity": 2}, {"quantity": 2}):
        res = client.post(f"{BASE}/orders/preview", json=data)
        assert res.status_code == 200, data
        assert res.json()["computed"]["total_cost"] is None, data


def test_order_validation(client):
    kit, service = article_id(KIT), article_id("Heure de conception graphique")

    def post(data):
        return client.post(f"{BASE}/orders", json=data)

    line = {"article_id": kit, "quantity": 1}
    cases = (
        ({}, "Article à fabriquer : obligatoire."),
        ({"quantity": 1}, "Article à fabriquer : obligatoire."),
        ({"article_id": 999999, "quantity": 1}, "Article à fabriquer : fiche introuvable."),
        ({"article_id": 10**20, "quantity": 1}, "Article à fabriquer : nombre hors limites."),
        ({"article_id": service, "quantity": 1}, "Article à fabriquer : un service ne se fabrique pas."),
        ({"article_id": kit}, "Quantité : obligatoire."),
        ({"article_id": kit, "quantity": None}, "Quantité : obligatoire."),
        ({"article_id": kit, "quantity": 0}, "Quantité : elle doit être positive."),
        ({"article_id": kit, "quantity": -2}, "Quantité : elle doit être positive."),
        ({"article_id": kit, "quantity": "beaucoup"}, "Quantité : nombre attendu."),
        ({**line, "planned_start": _day(), "planned_end": _day(-1)}, "Fin prévue : elle ne peut pas précéder le début prévu."),
        ({**line, "planned_end": "31/02/2026"}, "Fin prévue : date invalide."),
        ({**line, "warehouse_id": 999999}, "Entrepôt : fiche introuvable."),
        ({**line, "notes": "x" * 5001}, "Notes : 5000 caractères au plus."),
    )
    for data, message in cases:
        assert _error(post(data)) == message, data
    assert _error(post({"article_id": kit, "quantity": 2_000_000_000})).startswith("Quantité : ")
    # la fin prévue peut tomber le jour du début ; une quantité décimale est permise (« 2,5 »)
    order = post({**line, "quantity": "2,5", "planned_start": _day(3), "planned_end": _day(3)}).json()
    assert order["quantity"] == 2.5 and order["planned_end"] == _day(3)
    # en modification, les mêmes règles
    assert _error(client.put(f"{BASE}/orders/{order['id']}", json={"planned_end": _day(1)})) == \
        "Fin prévue : elle ne peut pas précéder le début prévu."
    assert _error(client.put(f"{BASE}/orders/{order['id']}", json={"article_id": service})) == \
        "Article à fabriquer : un service ne se fabrique pas."
    assert _error(client.put(f"{BASE}/orders/{order['id']}", json={"quantity": 0})) == "Quantité : elle doit être positive."
    # un brouillon dont l'article est devenu un service reste modifiable, mais ne se lance pas
    article = _post(client, f"{TECH}/articles", {"name": "Atelier découverte", "kind": "finished"})
    draft = _order(client, article["id"], 1)
    client.put(f"{TECH}/articles/{article['id']}", json={"kind": "service"})
    assert client.put(f"{BASE}/orders/{draft['id']}", json={"notes": "Pour le salon"}).status_code == 200
    assert _error(_act(client, draft, "release")) == "Article à fabriquer : un service ne se fabrique pas."
    # un brouillon sans quantité (donnée ancienne ou corrigée à la main) s'affiche, mais ne se lance pas
    db.execute("UPDATE production_orders SET quantity = NULL WHERE id = ?", (order["id"],))
    record = client.get(f"{BASE}/orders/{order['id']}").json()
    assert record["components"] == [] and record["total_cost"] is None and record["unit_cost"] is None
    assert _error(_act(client, order, "release")) == "Quantité : elle doit être positive."


# ═════════════════════════════════════════════════════════════════════════
# Coûts, manques, lancement
# ═════════════════════════════════════════════════════════════════════════
def test_costs_from_cost_prices_and_routing(client):
    p = _product(client)
    order = _order(client, p["box"], 10)
    # besoins pour 10 coffrets (5 fois la nomenclature) : 3 × 5 × 1,10 cartons, 5 rubans, 5 calages
    assert [(c["article_id"], c["quantity"]) for c in order["components"]] == [(p["board"], 16.5), (p["ribbon"], 5),
                                                                               (p["wedge"], 5)]
    # matière : 16,5 × 0,80 + 5 × 1,30 + 5 × 1,60 (calage : ½ carton à 0,80 + 2 min de pliage à 36 €/h) = 27,70
    assert technical.cost_price(p["wedge"]) == pytest.approx(1.6)
    assert order["material_cost"] == 27.7
    # opérations : dorure 30 + 3 × 10 = 60 min à 60 €/h, pliage 5 × 10 = 50 min à 36 €/h
    assert [(o["planned_minutes"], o["cost"]) for o in order["operations"]] == [(60, 60), (50, 30)]
    assert (order["labour_cost"], order["total_cost"], order["unit_cost"]) == (90, 117.7, 11.77)
    released = _run(client, order, "release")["row"]
    assert {k: released[k] for k in ("material_cost", "labour_cost", "total_cost", "unit_cost")} == \
        {"material_cost": 27.7, "labour_cost": 90, "total_cost": 117.7, "unit_cost": 11.77}
    listed = _listed(client, order)
    assert (listed["material_cost"], listed["labour_cost"], listed["unit_cost"]) == (27.7, 90, 11.77)
    # les coûts ne sont pas figés : ils suivent les prix (carton à 1,00 €, calage à 1,70 €)
    client.put(f"{TECH}/articles/{p['board']}", json={"purchase_price": 1})
    client.put(f"{TECH}/workcenters/{p['press']}", json={"hourly_cost": 72})
    record = client.get(f"{BASE}/orders/{order['id']}").json()
    assert (record["material_cost"], record["labour_cost"], record["total_cost"]) == (31.5, 102, 133.5)
    # sans gamme : pas de coût des opérations ; sans nomenclature ni gamme : aucun coût
    plain = _post(client, f"{TECH}/articles", {"name": "Marque-page", "kind": "finished"})
    _post(client, f"{TECH}/boms", {"article_id": plain["id"], "lines": [{"article_id": p["ribbon"], "quantity": 0.2}]})
    bare = _order(client, plain["id"], 10)
    assert (bare["material_cost"], bare["labour_cost"], bare["total_cost"], bare["unit_cost"]) == (2.6, None, 2.6, 0.26)
    assert bare["operations"] == []
    nothing = _order(client, _post(client, f"{TECH}/articles", {"name": "Prototype", "kind": "finished"})["id"], 3)
    assert nothing["components"] == [] and [nothing[k] for k in FIGURES] == [None, None, None, None, 0, False]


def test_completed_order_keeps_its_costs(client):
    """Un ordre terminé garde les coûts du jour de la fin de fabrication ; un ordre en cours suit les prix."""
    p = _product(client)
    done = _order(client, p["box"], 10)
    _run(client, done, "release")
    _run(client, done, "complete")
    running = _order(client, p["box"], 10)
    _run(client, running, "release")
    keys = ("material_cost", "labour_cost", "total_cost", "unit_cost")
    before = client.get(f"{BASE}/orders/{done['id']}").json()
    assert tuple(before[k] for k in keys) == (27.7, 90, 117.7, 11.77)
    client.put(f"{TECH}/articles/{p['board']}", json={"purchase_price": 1})
    client.put(f"{TECH}/workcenters/{p['press']}", json={"hourly_cost": 72})
    after = client.get(f"{BASE}/orders/{done['id']}").json()
    assert tuple(after[k] for k in keys) == (27.7, 90, 117.7, 11.77)
    assert [o["cost"] for o in after["operations"]] == [60, 30]
    assert tuple(_listed(client, done)[k] for k in keys) == (27.7, 90, 117.7, 11.77)
    moving = client.get(f"{BASE}/orders/{running['id']}").json()
    assert (moving["material_cost"], moving["labour_cost"]) == (31.5, 102)


def test_shortages_follow_the_stock(client):
    p = _product(client)
    _receive(client, p["board"], 10)
    _receive(client, p["ribbon"], 5)
    order = _order(client, p["box"], 10)
    lines = {c["article_id"]: (c["available"], c["shortage"]) for c in order["components"]}
    assert lines == {p["board"]: (10, 6.5), p["ribbon"]: (5, 0), p["wedge"]: (0, 5)}
    assert order["shortages"] == 2 and _listed(client, order)["shortages"] == 2
    # le lancement prévient des composants manquants
    res = _run(client, order, "release")
    assert res["message"] == (f"Ordre {order['code']} lancé. Stock insuffisant pour 2 composant(s) : "
                              "Carton gris 2 mm (il en manque 6,5), Calage carton (il en manque 5).")
    # un ordre lancé suit le stock du moment
    _receive(client, p["board"], 10)
    record = client.get(f"{BASE}/orders/{order['id']}").json()
    assert {c["article_id"]: c["shortage"] for c in record["components"]} == {p["board"]: 0, p["ribbon"]: 0, p["wedge"]: 5}
    assert record["shortages"] == 1
    # stock suffisant : lancement sans avertissement
    _receive(client, p["wedge"], 5)
    assert _run(client, _order(client, p["box"], 10), "release")["message"].endswith("lancé.")
    # entrepôt choisi : le stock disponible est celui de cet entrepôt
    reserve = _post(client, "/api/data/stock/warehouses", {"name": "Dépôt de dorure"})
    _receive(client, p["wedge"], 8, reserve["id"])
    local = _order(client, p["box"], 10, warehouse_id=reserve["id"])
    assert local["warehouse_id__label"] == "Dépôt de dorure"
    assert {c["article_id"]: (c["available"], c["shortage"]) for c in local["components"]} == {
        p["board"]: (0, 16.5), p["ribbon"]: (0, 5), p["wedge"]: (8, 0)}
    assert local["shortages"] == 2
    # un service dans une nomenclature ne se stocke pas : ni stock, ni manque
    design = article_id("Heure de conception graphique")
    custom = _post(client, f"{TECH}/articles", {"name": "Faire-part sur mesure", "kind": "finished"})
    _post(client, f"{TECH}/boms", {"article_id": custom["id"], "lines": [{"article_id": design, "quantity": 0.5},
                                                                          {"article_id": p["ribbon"], "quantity": 1}]})
    mixed = _order(client, custom["id"], 100)
    assert [(c["quantity"], c["available"], c["shortage"]) for c in mixed["components"]] == [(50, None, None), (100, 5, 95)]
    assert mixed["shortages"] == 1


def test_release_stores_components_and_operations(client):
    p = _product(client)
    order = _order(client, p["box"], 10, planned_end=_day(7))
    res = _run(client, order, "release")
    assert res["message"].startswith(f"Ordre {order['code']} lancé. Stock insuffisant pour 3 composant(s) : ")
    row = res["row"]
    assert row["status"] == "released" and row["bom_id"] == p["bom"]
    assert row["_locked"] == "Ordre lancé : il ne se modifie plus. Annulez-le et créez-en un autre si besoin."
    assert set(row["_actions"]) == {"complete", "cancel"} and row["_deletable"] is False
    components, operations = _stored(order)
    assert components == [(0, p["board"], 16.5), (1, p["ribbon"], 5), (2, p["wedge"], 5)]
    assert operations == [(0, p["press"], "Dorure à chaud", 60), (1, p["folding"], "Pliage et assemblage", 50)]
    assert [c["article_id__label"] for c in row["components"]] == ["Carton gris 2 mm", "Ruban satin doré", "Calage carton"]
    assert [o["workcenter_id__label"] for o in row["operations"]] == ["Presse à dorer", "Poste de pliage"]
    # verrouillé : ni modification, ni second lancement
    assert _error(client.put(f"{BASE}/orders/{order['id']}", json={"notes": "x"}), 409) == row["_locked"]
    assert _error(_act(client, order, "release"), 409) == "Cette action n'est pas possible dans l'état actuel de la fiche."
    # les besoins sont figés au lancement ; un nouveau brouillon suit la nomenclature et la gamme modifiées
    client.put(f"{TECH}/boms/{p['bom']}", json={"lines": [{"article_id": p["ribbon"], "quantity": 2}]})
    client.put(f"{TECH}/routings/{p['routing']}", json={"steps": [
        {"workcenter_id": p["press"], "description": "Dorure à chaud", "setup_minutes": 15, "run_minutes": 3}]})
    record = client.get(f"{BASE}/orders/{order['id']}").json()
    assert [(c["article_id"], c["quantity"]) for c in record["components"]] == [(p["board"], 16.5), (p["ribbon"], 5),
                                                                                (p["wedge"], 5)]
    assert [o["planned_minutes"] for o in record["operations"]] == [60, 50] and _stored(order) == (components, operations)
    draft = _order(client, p["box"], 10)
    assert [(c["article_id"], c["quantity"]) for c in draft["components"]] == [(p["ribbon"], 10)]
    assert [o["planned_minutes"] for o in draft["operations"]] == [45]


def test_release_requires_an_active_bill(client):
    article = _post(client, f"{TECH}/articles", {"name": "Carnet de croquis", "kind": "finished"})
    order = _order(client, article["id"], 5)
    assert order["components"] == [] and order["operations"] == []
    assert _error(_act(client, order, "release")) == NO_BOM
    # une nomenclature inactive ne compte pas
    paper = article_id(PAPER)
    bom = _post(client, f"{TECH}/boms", {"article_id": article["id"], "active": False,
                                         "lines": [{"article_id": paper, "quantity": 12}]})
    assert _error(_act(client, order, "release")) == NO_BOM
    row = client.get(f"{BASE}/orders/{order['id']}").json()
    assert row["status"] == "draft" and row["bom_id"] is None and _stored(order) == ([], [])
    client.put(f"{TECH}/boms/{bom['id']}", json={"active": True})
    released = _run(client, order, "release")["row"]
    assert released["status"] == "released" and released["bom_id"] == bom["id"]
    assert _stored(order) == ([(0, paper, 60)], [])  # sans gamme : aucune opération
    assert released["labour_cost"] is None and released["operations"] == []


# ═════════════════════════════════════════════════════════════════════════
# Fin de fabrication : mouvements de stock, événement
# ═════════════════════════════════════════════════════════════════════════
def test_completion_moves_stock_once(client):
    p = _product(client)
    _receive(client, p["board"], 20)
    _receive(client, p["ribbon"], 10)
    _receive(client, p["wedge"], 5)
    articles = (p["box"], p["board"], p["ribbon"], p["wedge"])
    before = {a: stock.on_hand(a) for a in articles}
    order = _order(client, p["box"], 10)
    _run(client, order, "release")
    assert {a: stock.on_hand(a) for a in articles} == before and not _moves(order)  # lancé : rien ne bouge encore
    month = _kpis(client)["production.completed_month"]["value"]
    res = _run(client, order, "complete")
    assert res["message"] == f"Ordre {order['code']} terminé. Stock : 4 mouvement(s) enregistré(s)."
    row = res["row"]
    assert row["status"] == "done" and row["produced_quantity"] == 10 and row["completed_on"] == _day()
    main = stock.default_warehouse_id()
    assert row["warehouse_id"] == main and row["warehouse_id__label"] == "Entrepôt principal"
    assert row["_actions"] == [] and row["_locked"] == "Ordre terminé : il ne se modifie plus." and row["_deletable"] is False
    assert row["shortages"] is None and all(c["available"] is None and c["shortage"] is None for c in row["components"])
    assert row["total_cost"] == 117.7
    # le produit entre (+10), les composants sortent (besoins enregistrés au lancement)
    assert stock.on_hand(p["box"]) == before[p["box"]] + 10
    assert stock.on_hand(p["board"]) == pytest.approx(before[p["board"]] - 16.5)
    assert stock.on_hand(p["ribbon"]) == before[p["ribbon"]] - 5 and stock.on_hand(p["wedge"]) == before[p["wedge"]] - 5
    assert _moves(order) == [("production", p["box"], 10, main, _day(), order["code"]),
                             ("consumption", p["board"], -16.5, main, _day(), order["code"]),
                             ("consumption", p["ribbon"], -5, main, _day(), order["code"]),
                             ("consumption", p["wedge"], -5, main, _day(), order["code"])]
    assert _kpis(client)["production.completed_month"]["value"] == month + 1
    # une seule fois : ni seconde fin, ni annulation, et la Logistique ne compte jamais deux fois
    for action in ("complete", "cancel", "release"):
        assert _act(client, order, action).status_code == 409, action
    assert stock.on_production_completed({"order_id": order["id"], "code": order["code"], "article_id": p["box"],
                                          "quantity": 10, "components": []}) is None
    assert stock.on_hand(p["box"]) == before[p["box"]] + 10 and len(_moves(order)) == 4
    # terminé : ne se supprime plus
    assert _error(client.delete(f"{BASE}/orders/{order['id']}"), 409) == "Seul un ordre en brouillon ou annulé peut être supprimé."


def test_completion_event_payload(client, monkeypatch):
    seen = []

    def listener(payload):
        status = db.fetch_one("SELECT status FROM production_orders WHERE id = ?", (payload["order_id"],))["status"]
        seen.append((payload, status))
        return "Comptabilité prévenue."

    monkeypatch.setattr(registry.get("accounting"), "events", {"production.order_completed": listener})
    p = _product(client)
    reserve = _post(client, "/api/data/stock/warehouses", {"name": "Dépôt de dorure"})
    order = _order(client, p["box"], 10, warehouse_id=reserve["id"])
    _run(client, order, "release")
    assert not seen  # le lancement n'annonce rien
    res = _run(client, order, "complete")
    assert res["message"] == (f"Ordre {order['code']} terminé. Stock : 4 mouvement(s) enregistré(s). "
                              "Comptabilité prévenue.")
    [(payload, status)] = seen
    assert status == "released"  # l'événement part avant que la fin soit enregistrée
    assert payload == {
        "order_id": order["id"], "code": order["code"], "date": _day(), "article_id": p["box"], "quantity": 10,
        "warehouse_id": reserve["id"],
        "components": [{"article_id": p["board"], "quantity": 16.5}, {"article_id": p["ribbon"], "quantity": 5},
                       {"article_id": p["wedge"], "quantity": 5}],
    }
    assert stock.on_hand(p["box"], reserve["id"]) == 10 and stock.on_hand(p["board"], reserve["id"]) == -16.5
    # sans entrepôt : celui par défaut, annoncé et retenu sur l'ordre
    other = _order(client, p["box"], 2)
    _run(client, other, "release")
    done = _run(client, other, "complete")["row"]
    assert seen[1][0]["warehouse_id"] == stock.default_warehouse_id() == done["warehouse_id"]
    # l'annulation n'annonce rien
    cancelled = _order(client, p["box"], 2)
    _run(client, cancelled, "release")
    _run(client, cancelled, "cancel")
    assert len(seen) == 2


def test_subscriber_error_cancels_the_completion(client, monkeypatch):
    def refuse(_payload):
        raise ValueError("Inventaire en cours : réessayez demain.")

    monkeypatch.setattr(registry.get("accounting"), "events", {"production.order_completed": refuse})
    p = _product(client)
    order = _order(client, p["box"], 4)
    _run(client, order, "release")
    before = stock.on_hand(p["box"])
    assert _error(_act(client, order, "complete")) == "Inventaire en cours : réessayez demain."
    row = client.get(f"{BASE}/orders/{order['id']}").json()
    assert row["status"] == "released" and row["completed_on"] is None and row["produced_quantity"] is None
    assert set(row["_actions"]) == {"complete", "cancel"}
    # l'abonné rétabli, la fin passe et le stock n'est compté qu'une fois
    monkeypatch.setattr(registry.get("accounting"), "events", {})
    assert _run(client, order, "complete")["row"]["status"] == "done"
    assert stock.on_hand(p["box"]) == before + 4 and len(_moves(order)) == 4


# ═════════════════════════════════════════════════════════════════════════
# Annulation, verrouillage, suppression
# ═════════════════════════════════════════════════════════════════════════
def test_cancel_lock_and_delete(client):
    p = _product(client)
    draft = _order(client, p["box"], 4)
    res = _run(client, draft, "cancel")
    assert res["message"] == f"Ordre {draft['code']} annulé."
    row = res["row"]
    assert row["status"] == "cancelled" and row["_actions"] == [] and row["_locked"] == "Ordre annulé : il ne se modifie plus."
    assert row["components"] == [] and row["total_cost"] is None and row["shortages"] is None
    for action in ("release", "complete", "cancel"):
        assert _act(client, draft, action).status_code == 409, action
    assert client.put(f"{BASE}/orders/{draft['id']}", json={"notes": "x"}).status_code == 409
    # verrouillé mais supprimable : la règle du module décide
    assert row["_deletable"] is True and client.delete(f"{BASE}/orders/{draft['id']}").status_code == 204
    assert client.get(f"{BASE}/orders/{draft['id']}").status_code == 404

    released = _order(client, p["box"], 6)
    _run(client, released, "release")
    assert _error(client.delete(f"{BASE}/orders/{released['id']}"), 409) == \
        "Seul un ordre en brouillon ou annulé peut être supprimé."
    cancelled = _run(client, released, "cancel")["row"]
    assert cancelled["status"] == "cancelled" and not _moves(released)  # rien n'est entré ni sorti du stock
    # les besoins enregistrés au lancement restent lisibles, sans stock disponible ni manque
    assert [(c["quantity"], c["available"]) for c in cancelled["components"]] == [(9.9, None), (3, None), (3, None)]
    assert cancelled["total_cost"] is not None and cancelled["shortages"] is None
    assert _act(client, released, "complete").status_code == 409
    assert client.delete(f"{BASE}/orders/{released['id']}").status_code == 204
    assert _stored(released) == ([], [])  # ses lignes partent avec lui

    spare = _order(client, p["box"], 1)
    assert client.delete(f"{BASE}/orders/{spare['id']}").status_code == 204
    assert client.post(f"{BASE}/orders/{spare['id']}/actions/release").status_code == 404
    order = _order(client, p["box"], 1)
    assert client.post(f"{BASE}/orders/{order['id']}/actions/inconnue").status_code == 404


def test_lock_and_delete_rules_by_status():
    ORDERS.before_delete({"status": "draft"})
    ORDERS.before_delete({"status": "cancelled"})
    for status in ("released", "done"):
        with pytest.raises(Conflict, match="Seul un ordre en brouillon ou annulé peut être supprimé."):
            ORDERS.before_delete({"status": status})
    assert ORDERS.locked({"status": "draft"}) is None
    assert all(ORDERS.locked({"status": status}) for status in ("released", "done", "cancelled"))


def test_an_action_never_passes_twice(client):
    """Deux clics (ou deux personnes) sur la même fiche : la seconde action, partie d'une fiche périmée, est refusée."""
    p = _product(client)
    order = _order(client, p["box"], 2)
    actions = {a.key: a for a in ORDERS.actions}
    stale = client.get(f"{BASE}/orders/{order['id']}").json()
    _run(client, order, "release")
    with pytest.raises(Conflict, match="L'ordre de fabrication vient d'être modifié par ailleurs : rechargez-le."):
        actions["release"].run(stale, {}, {})
    assert len(_stored(order)[0]) == 3  # les besoins ne sont pas enregistrés deux fois
    stale = client.get(f"{BASE}/orders/{order['id']}").json()
    _run(client, order, "complete")
    with pytest.raises(Conflict):
        actions["complete"].run(stale, {}, {})
    with pytest.raises(Conflict):
        actions["cancel"].run(stale, {}, {})
    row = client.get(f"{BASE}/orders/{order['id']}").json()
    assert row["status"] == "done" and len(_moves(order)) == 4  # la Logistique ne compte pas deux fois


def test_used_records_cannot_be_deleted(client):
    p = _product(client)
    reserve = _post(client, "/api/data/stock/warehouses", {"name": "Dépôt de dorure"})
    order = _order(client, p["box"], 10, warehouse_id=reserve["id"])
    _run(client, order, "release")
    # la nomenclature et le poste ne sont plus désignés que par l'ordre lancé
    client.put(f"{TECH}/routings/{p['routing']}", json={"steps": [
        {"workcenter_id": p["folding"], "description": "Pliage et assemblage", "run_minutes": 5}]})
    used = "Suppression impossible : cette fiche est utilisée ailleurs (ordres de fabrication : 1)."
    assert _error(client.delete(f"{TECH}/workcenters/{p['press']}"), 409) == used
    assert _error(client.delete(f"{TECH}/boms/{p['bom']}"), 409) == used
    assert _error(client.delete(f"/api/data/stock/warehouses/{reserve['id']}"), 409) == used
    assert "ordres de fabrication : 1" in _error(client.delete(f"{TECH}/articles/{p['box']}"), 409)
    # l'ordre annulé puis supprimé, plus rien ne les retient
    _run(client, order, "cancel")
    assert client.delete(f"{BASE}/orders/{order['id']}").status_code == 204
    assert client.delete(f"{TECH}/workcenters/{p['press']}").status_code == 204
    assert client.delete(f"{TECH}/boms/{p['bom']}").status_code == 204
    assert client.delete(f"/api/data/stock/warehouses/{reserve['id']}").status_code == 204


# ═════════════════════════════════════════════════════════════════════════
# Charge des postes
# ═════════════════════════════════════════════════════════════════════════
def test_load_counts_released_orders_only(client):
    p = _product(client)
    load = _load(client)
    assert {k: load["Presse à dorer"][k] for k in ("capacity_hours", "planned_hours", "orders", "load_days")} == \
        {"capacity_hours": 7, "planned_hours": 0, "orders": 0, "load_days": 0}
    assert load["Poste de pliage"]["capacity_hours"] is None and load["Poste de pliage"]["load_days"] is None
    _order(client, p["box"], 10)                                       # brouillon : ne charge pas les postes
    _run(client, _order(client, p["box"], 10), "release")              # dorure 60 min, pliage 50 min
    _run(client, _order(client, p["box"], 4), "release")               # dorure 30 + 12 min, pliage 20 min
    done = _order(client, p["box"], 2)
    _run(client, done, "release")
    _run(client, done, "complete")                                     # terminé : ne charge plus
    cancelled = _order(client, p["box"], 6)
    _run(client, cancelled, "release")
    _run(client, cancelled, "cancel")                                  # annulé : ne charge plus
    load = _load(client)
    press, folding = load["Presse à dorer"], load["Poste de pliage"]
    # 102 min = 1,7 h sur 7 h par jour ; 70 min = 1,17 h, sans capacité renseignée
    assert (press["planned_hours"], press["orders"], press["load_days"]) == (1.7, 2, 0.24)
    assert (folding["planned_hours"], folding["orders"], folding["load_days"]) == (1.17, 2, None)
    assert press["workcenter_id"] == press["id"] == p["press"] and press["workcenter_id__label"] == "Presse à dorer"
    record = client.get(f"{BASE}/load/{p['press']}").json()
    assert (record["workcenter_name"], record["planned_hours"], record["load_days"]) == ("Presse à dorer", 1.7, 0.24)
    found = client.get(f"{BASE}/load", params={"q": "dorer"}).json()["rows"]
    assert [r["id"] for r in found] == [p["press"]]
    assert client.get(f"{BASE}/load", params={"sort": "planned_hours", "dir": "desc"}).status_code == 200
    # consultation seulement
    assert client.post(f"{BASE}/load", json={}).status_code == 409
    assert client.put(f"{BASE}/load/{p['press']}", json={"capacity_hours": 8}).status_code == 409
    assert client.delete(f"{BASE}/load/{p['press']}").status_code == 409
    # la capacité vient du poste : la changer change la charge en jours
    client.put(f"{TECH}/workcenters/{p['folding']}", json={"capacity_hours": 3.5})
    assert _load(client)["Poste de pliage"]["load_days"] == round(1.17 / 3.5, 2)


# ═════════════════════════════════════════════════════════════════════════
# Droits, activation, description, chiffres clés, export
# ═════════════════════════════════════════════════════════════════════════
def test_production_role_runs_the_workshop(client):
    p = _product(client)
    make_member("atelier@test.local", "production")
    worker = login_as("atelier@test.local")
    meta = worker.get("/api/meta").json()
    keys = [m["key"] for m in meta["modules"]]
    assert {"production", "technical", "stock"} <= set(keys) and "sales" not in keys
    assert meta["levels"]["production"] == 2
    orders = meta["entities"]["production.orders"]
    assert orders["can_create"] and orders["can_edit"] and not orders["can_delete"]
    assert not meta["entities"]["production.load"]["can_create"]
    order = worker.post(f"{BASE}/orders", json={"article_id": p["box"], "quantity": 2})
    assert order.status_code == 201, order.text
    order = order.json()
    assert worker.post(f"{BASE}/orders/preview", json={"article_id": p["box"], "quantity": 2}).status_code == 200
    assert worker.post(f"{BASE}/orders/{order['id']}/actions/release").status_code == 200
    completed = worker.post(f"{BASE}/orders/{order['id']}/actions/complete")
    assert completed.status_code == 200 and "Stock : 4 mouvement(s)" in completed.json()["message"]
    assert worker.get(f"{BASE}/load").status_code == 200
    # suppression : niveau gestion, que la production n'a pas
    draft = worker.post(f"{BASE}/orders", json={"article_id": p["box"], "quantity": 1}).json()
    assert worker.delete(f"{BASE}/orders/{draft['id']}").status_code == 403
    assert worker.post(f"{BASE}/orders/{draft['id']}/actions/cancel").status_code == 200
    assert worker.delete(f"{BASE}/orders/{draft['id']}").status_code == 403
    home = worker.get("/api/home").json()
    assert {"production.in_progress", "production.late", "production.completed_month"} <= {k["key"] for k in home["kpis"]}
    assert "production.new_order" in {s["key"] for s in home["shortcuts"]}


def test_readonly_and_other_roles(client):
    p = _product(client)
    draft = _order(client, p["box"], 2)
    released = _order(client, p["box"], 3)
    _run(client, released, "release")
    make_member("lecture-production@test.local", "readonly")
    reader = login_as("lecture-production@test.local")
    assert reader.get(f"{BASE}/orders").status_code == 200 and reader.get(f"{BASE}/load").status_code == 200
    assert reader.get(f"{BASE}/orders/export").status_code == 200
    record = reader.get(f"{BASE}/orders/{draft['id']}").json()
    assert record["_actions"] == [] and record["_deletable"] is False and record["components"]
    assert reader.post(f"{BASE}/orders", json={"article_id": p["box"], "quantity": 1}).status_code == 403
    assert reader.put(f"{BASE}/orders/{draft['id']}", json={"notes": "x"}).status_code == 403
    assert reader.post(f"{BASE}/orders/preview", json={}).status_code == 403
    for order, action in ((draft, "release"), (draft, "cancel"), (released, "complete"), (released, "cancel")):
        assert reader.post(f"{BASE}/orders/{order['id']}/actions/{action}").status_code == 403, action
    assert reader.delete(f"{BASE}/orders/{draft['id']}").status_code == 403
    meta = reader.get("/api/meta").json()["entities"]["production.orders"]
    assert not meta["can_create"] and not meta["can_edit"] and not meta["can_delete"]
    home = reader.get("/api/home").json()
    assert "production.in_progress" in {k["key"] for k in home["kpis"]}
    assert "production.new_order" not in {s["key"] for s in home["shortcuts"]}  # raccourci : niveau écriture
    assert client.get(f"{BASE}/orders/{draft['id']}").json()["status"] == "draft"
    assert client.get(f"{BASE}/orders/{released['id']}").json()["status"] == "released"
    # un commercial n'a pas accès à la production ; une dérogation en écriture la lui donne, sans la suppression
    seller = make_member("commercial-atelier@test.local", "sales")
    member = login_as("commercial-atelier@test.local")
    assert member.get(f"{BASE}/orders").status_code == 403
    assert "production.in_progress" not in {k["key"] for k in member.get("/api/home").json()["kpis"]}
    client.put(f"/api/users/{seller['id']}/permissions", json={"overrides": {"production": "write"}})
    created = member.post(f"{BASE}/orders", json={"article_id": p["box"], "quantity": 1})
    assert created.status_code == 201
    assert member.delete(f"{BASE}/orders/{created.json()['id']}").status_code == 403


def test_dependencies_stay_on_while_production_is_on(client, restore_modules):
    res = client.put("/api/settings/modules/stock", json={"enabled": False})
    assert _error(res, 409) == "Désactivez d'abord les modules qui en dépendent : Production."
    assert "Production" in _error(client.put("/api/settings/modules/technical", json={"enabled": False}), 409)
    assert registry.is_enabled("stock") and registry.is_enabled("technical")


def test_disabled_production_disappears(client, restore_modules):
    p = _product(client)
    order = _order(client, p["box"], 3)
    _run(client, order, "release")
    disable_module(client, "production")
    assert client.get(f"{BASE}/orders").status_code == 404
    assert client.get(f"{BASE}/orders/{order['id']}").status_code == 404
    assert client.get(f"{BASE}/load").status_code == 404
    assert client.post(f"{BASE}/orders", json={"article_id": p["box"], "quantity": 1}).status_code == 404
    assert client.post(f"{BASE}/orders/{order['id']}/actions/complete").status_code == 404
    meta = client.get("/api/meta").json()
    assert "production" not in [m["key"] for m in meta["modules"]]
    assert "production.orders" not in meta["entities"] and "production.load" not in meta["entities"]
    home = client.get("/api/home").json()
    assert not [k for k in home["kpis"] if k["module"] == "production"]
    assert not [s for s in home["shortcuts"] if s["module"] == "production"]
    # ses données restent, et protègent toujours les fiches qu'elles désignent
    assert "ordres de fabrication : 1" in _error(client.delete(f"{TECH}/articles/{p['box']}"), 409)
    # la Logistique peut maintenant être désactivée ; la Production ne revient pas sans elle
    assert client.put("/api/settings/modules/stock", json={"enabled": False}).status_code == 200
    assert _error(client.put("/api/settings/modules/production", json={"enabled": True}), 409) == "Activez d'abord : Logistique."
    assert client.put("/api/settings/modules/stock", json={"enabled": True}).status_code == 200
    assert client.put("/api/settings/modules/production", json={"enabled": True}).status_code == 200
    back = client.get(f"{BASE}/orders/{order['id']}").json()
    assert back["code"] == order["code"] and back["status"] == "released"


def test_production_works_without_unrelated_modules(client, restore_modules):
    for key in ("sales", "purchases", "hr", "accounting"):
        disable_module(client, key)
    p = _product(client)
    _receive(client, p["board"], 20)
    order = _order(client, p["box"], 10)
    assert order["shortages"] == 2 and order["total_cost"] == 117.7
    _run(client, order, "release")
    res = _run(client, order, "complete")
    assert res["message"] == f"Ordre {order['code']} terminé. Stock : 4 mouvement(s) enregistré(s)."
    assert stock.on_hand(p["box"]) == 10 and stock.on_hand(p["board"]) == 3.5
    assert client.get(f"{BASE}/load").status_code == 200 and client.get("/api/home").status_code == 200


def test_meta_describes_the_module(client):
    meta = client.get("/api/meta").json()
    module = next(m for m in meta["modules"] if m["key"] == "production")
    assert module["slug"] == "production" and module["label"] == ["Production", "Production"] and module["icon"] == "Factory"
    assert [(p["slug"], p["entity"]) for p in module["pages"]] == [("ordres", "production.orders"), ("charge", "production.load")]
    orders = meta["entities"]["production.orders"]
    assert orders["label"] == ["Ordre de fabrication", "Manufacturing order"] and orders["title"] == "code"
    assert orders["board"] == "status" and not orders["readonly"]
    assert [a["key"] for a in orders["actions"]] == ["release", "complete", "cancel"]
    assert [a["key"] for a in orders["actions"] if a["confirm"]] == ["complete", "cancel"]
    assert all(a["level"] == 2 for a in orders["actions"])
    assert next(a for a in orders["actions"] if a["key"] == "cancel")["style"] == "danger"
    fields = {f["name"]: f for f in orders["fields"]}
    assert [name for name, f in fields.items() if f["list"]] == ["code", "article_id", "quantity", "planned_start",
                                                                 "planned_end", "status", "shortages", "late"]
    assert fields["code"]["prefix"] == "OF" and fields["code"]["readonly"] and fields["code"]["search"]
    assert fields["article_id"]["label"] == ["Article à fabriquer", "Item to make"]
    assert fields["article_id"]["required"] and fields["article_id"]["filter"] and fields["article_id"]["ref"] == "technical.articles"
    assert fields["quantity"]["required"] and fields["warehouse_id"]["ref"] == "stock.warehouses"
    assert not fields["warehouse_id"]["required"] and fields["warehouse_id"]["label"][0] == "Entrepôt"
    assert [c["value"] for c in fields["status"]["choices"]] == ["draft", "released", "done", "cancelled"]
    assert [c["label"][0] for c in fields["status"]["choices"]] == ["Brouillon", "Lancé", "Terminé", "Annulé"]
    assert fields["status"]["readonly"] and fields["status"]["filter"] and fields["status"]["default"] == "draft"
    assert fields["produced_quantity"]["readonly"] and fields["completed_on"]["readonly"]
    assert [name for name, f in fields.items() if f["computed"]] == ["material_cost", "labour_cost", "total_cost",
                                                                     "unit_cost", "shortages", "late"]
    assert "bom_id" not in fields  # lu avec la fiche, jamais affiché
    components, operations = orders["children"]
    assert (components["key"], operations["key"]) == ("components", "operations")
    assert not components["writable"] and not operations["writable"]
    assert [f["name"] for f in components["fields"]] == ["article_id", "quantity", "available", "shortage"]
    assert [f["label"][0] for f in components["fields"]] == ["Composant", "Besoin", "En stock", "Manquant"]
    assert [f["name"] for f in operations["fields"]] == ["workcenter_id", "description", "planned_minutes", "cost"]
    assert all(f["readonly"] for f in components["fields"] + operations["fields"])
    load = meta["entities"]["production.load"]
    assert load["readonly"] and load["plural"] == ["Charge des postes", "Work centre load"] and not load["can_create"]
    assert [f["name"] for f in load["fields"] if f["list"]] == ["workcenter_name", "capacity_hours", "planned_hours",
                                                                "orders", "load_days"]


def test_home_kpis_follow_the_orders(client):
    start = _kpis(client)
    assert start["production.in_progress"]["path"] == "/production/ordres?f_status=released"
    assert start["production.late"]["path"].startswith("/production/ordres?f_status=released")
    assert start["production.completed_month"]["path"] == "/production/ordres?f_status=done"
    shortcut = next(s for s in client.get("/api/home").json()["shortcuts"] if s["key"] == "production.new_order")
    assert shortcut["path"] == "/production/ordres?new=1" and shortcut["label"] == ["Ordre de fabrication", "Manufacturing order"]
    p = _product(client)
    late = _order(client, p["box"], 2, planned_start=_day(-5), planned_end=_day(-1))
    due_today = _order(client, p["box"], 2, planned_end=_day())
    undated = _order(client, p["box"], 2)
    draft_late = _order(client, p["box"], 2, planned_start=_day(-5), planned_end=_day(-1))  # brouillon : pas en retard
    for order in (late, due_today, undated):
        _run(client, order, "release")
    now = _kpis(client)
    assert now["production.in_progress"]["value"] == start["production.in_progress"]["value"] + 3
    assert now["production.late"]["value"] == start["production.late"]["value"] + 1 and now["production.late"]["alert"] is True
    rows = {r["id"]: r for r in client.get(f"{BASE}/orders", params={"size": 200}).json()["rows"]}
    assert [rows[o["id"]]["late"] for o in (late, due_today, undated, draft_late)] == [True, False, False, False]
    _run(client, late, "complete")      # terminé : plus en cours, plus en retard, compté ce mois-ci
    _run(client, undated, "cancel")     # annulé : plus en cours
    end = _kpis(client)
    assert end["production.in_progress"]["value"] == start["production.in_progress"]["value"] + 1
    assert end["production.late"]["value"] == start["production.late"]["value"]
    assert end["production.completed_month"]["value"] == start["production.completed_month"]["value"] + 1
    assert client.get(f"{BASE}/orders/{late['id']}").json()["late"] is False
    # chaque chiffre clé correspond à la liste qu'il ouvre
    released = client.get(f"{BASE}/orders", params={"f_status": "released", "size": 200}).json()
    assert end["production.in_progress"]["value"] == released["total"]
    assert end["production.late"]["value"] == len([r for r in released["rows"] if r["late"]])
    month = today().replace(day=1).isoformat()
    done = client.get(f"{BASE}/orders", params={"f_status": "done", "size": 200}).json()["rows"]
    assert end["production.completed_month"]["value"] == len([r for r in done if r["completed_on"] >= month])
    # sans ordre en retard : pas d'alerte
    for row in released["rows"]:
        if row["late"]:
            client.post(f"{BASE}/orders/{row['id']}/actions/cancel")
    final = _kpis(client)["production.late"]
    assert (final["value"], final["alert"]) == (0, False)


def test_kpis_are_offered_in_my_views(client):
    """« Mes vues » reconnaît un chiffre clé quand la demande cite son libellé : chaque libellé nomme ce qu'il compte,
    et les demandes sur d'autres sujets ne font pas apparaître la production."""
    def metrics(text):
        widgets = dashboard.compose_offline(text, {})["spec"]["widgets"]
        return [w["params"]["metric"] for w in widgets if w["source"] == "kpi"]

    module = registry.get("production")
    assert [k.key for k in module.kpis] == ["in_progress", "late", "completed_month"]
    for kpi in module.kpis:
        for label in kpi.label:
            assert f"production.{kpi.key}" in metrics(f"Montre-moi : {label.lower()}"), label
    for text in ("mes factures en retard", "le total en retard", "combien j'ai encaissé ce mois-ci", "mes commandes à livrer",
                 "les commandes fournisseurs à recevoir", "les livraisons fournisseurs en retard"):
        assert not [m for m in metrics(text) if m.startswith("production.")], text
    res = client.post("/api/dashboards/compose", json={"text": "Montre-moi les ordres de fabrication en cours"})
    [card] = [w for w in res.json()["view"]["widgets"] if w["source"] == "kpi"]
    released = client.get(f"{BASE}/orders", params={"f_status": "released"}).json()["total"]
    assert card["params"]["metric"] == "production.in_progress" and card["data"]["value"] == released
    assert card["data"]["path"] == "/production/ordres?f_status=released"
    # sans accès à la production, ni la demande ni une vue enregistrée ne montrent ces chiffres
    make_member("commercial-vues-atelier@test.local", "sales")
    seller = login_as("commercial-vues-atelier@test.local")
    res = seller.post("/api/dashboards/compose", json={"text": "Montre-moi les ordres de fabrication en cours"}).json()
    assert not [w for w in res["view"]["widgets"] if w["params"].get("metric", "").startswith("production.")]
    hidden = seller.post("/api/dashboards/render", json={"spec": {"widgets": [
        {"source": "kpi", "params": {"metric": "production.late"}}]}}).json()
    assert hidden["widgets"] == [] and hidden["hidden"] == 1


def test_board_and_export(client):
    p = _product(client)
    order = _order(client, p["box"], 10, notes="Coffrets pour le salon")
    _run(client, order, "release")
    board = client.get(f"{BASE}/orders/board").json()
    assert board["field"] == "status" and board["amount_field"] is None
    columns = {c["value"]: c for c in board["columns"]}
    assert list(columns) == ["draft", "released", "done", "cancelled"]
    for status, column in columns.items():
        assert column["count"] == client.get(f"{BASE}/orders", params={"f_status": status}).json()["total"], status
    assert order["id"] in [r["id"] for r in columns["released"]["rows"]]
    res = client.get(f"{BASE}/orders/export", params={"q": order["code"]})
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    header, *rows = list(csv.reader(io.StringIO(res.text.lstrip("﻿")), delimiter=";"))
    [row] = rows
    cells = dict(zip(header, row, strict=True))
    assert cells["Numéro"] == order["code"] and cells["Article à fabriquer"] == "Coffret prestige"
    assert (cells["Quantité"], cells["Statut"], cells["Coût total"], cells["Coût unitaire"]) == ("10", "Lancé", "117,70", "11,77")
    assert (cells["Composants manquants"], cells["En retard"]) == ("3", "Non")
    assert "Nomenclature" not in cells  # champ caché
    english = client.get(f"{BASE}/orders/export", params={"q": order["code"], "lang": "en"}).text.lstrip("﻿")
    header, row = list(csv.reader(io.StringIO(english)))
    assert dict(zip(header, row, strict=True))["Total cost"] == "117.70"
    options = client.get(f"{BASE}/orders/options", params={"q": order["code"]}).json()
    assert [(o["id"], o["label"]) for o in options] == [(order["id"], order["code"])]


# ═════════════════════════════════════════════════════════════════════════
# Démonstration
# ═════════════════════════════════════════════════════════════════════════
def test_demo_data(client):
    rows = client.get(f"{BASE}/orders", params={"size": 200}).json()["rows"]
    demo = [r for r in rows if r["article_id__label"] in (KIT, CARDS)]
    assert sorted((r["article_id__label"], r["quantity"], r["status"]) for r in demo) == [
        (CARDS, 10, "draft"), (CARDS, 20, "released"), (KIT, 4, "done"), (KIT, 5, "released")]
    assert all(r["code"].startswith(f"OF-{today().year}-") for r in demo)
    # terminé : 4 kits entrés en stock, leurs composants consommés (besoins de la nomenclature, pertes comprises)
    done = next(r for r in demo if r["status"] == "done")
    record = client.get(f"{BASE}/orders/{done['id']}").json()
    assert record["produced_quantity"] == 4 and record["completed_on"] == _day()
    assert record["warehouse_id__label"] == "Entrepôt principal" and record["notes"]
    kit, cards = article_id(KIT), article_id(CARDS)
    needs = [(c["article_id__label"], c["quantity"]) for c in record["components"]]
    assert needs == [(CARDS, 4), ("Enveloppe kraft C5", 102), (PAPER, 41.2), ("Boîte cadeau kraft 22×16 cm", 4),
                     ("Papier de soie (feuille)", 16)]
    moves = _moves(record)
    assert moves[0] == ("production", kit, 4, record["warehouse_id"], _day(), record["code"])
    assert [(m[0], m[1], m[2]) for m in moves[1:]] == [("consumption", c["article_id"], -c["quantity"]) for c in record["components"]]
    assert (record["material_cost"], record["labour_cost"]) == (
        round(sum(c["quantity"] * technical.cost_price(c["article_id"]) for c in record["components"]), 2), 88.42)
    # lancés : 5 kits pour dans 4 jours, 20 jeux de cartes attendus il y a 2 jours (en retard) ; un brouillon
    kits = next(r for r in demo if r["status"] == "released" and r["article_id"] == kit)
    assert (kits["planned_end"], kits["late"]) == (_day(4), False)
    late = [r for r in demo if r["late"]]
    assert [(r["article_id"], r["quantity"], r["planned_end"]) for r in late] == [(cards, 20, _day(-2))]
    draft = next(r for r in demo if r["status"] == "draft")
    assert (draft["planned_start"], draft["material_cost"], draft["labour_cost"]) == (_day(3), round(52 * technical.cost_price(
        article_id(PAPER)), 2), 55)
    for order in demo:
        if order["status"] != "done":
            assert not _moves(order)  # seul l'ordre terminé a bougé le stock
    # charge : seuls les deux ordres lancés comptent
    load = _load(client)
    assert {name: (load[name]["planned_hours"], load[name]["orders"], load[name]["load_days"]) for name in
            ("Imprimante numérique", "Massicot", "Atelier de façonnage")} == {
        "Imprimante numérique": (2.42, 2, 0.35), "Massicot": (1.5, 2, 0.21), "Atelier de façonnage": (1.67, 1, 0.24)}
    kpis = _kpis(client)
    released = client.get(f"{BASE}/orders", params={"f_status": "released", "size": 200}).json()
    assert kpis["production.in_progress"]["value"] == released["total"] >= 2
    assert kpis["production.late"]["value"] == len([r for r in released["rows"] if r["late"]]) >= 1
    assert kpis["production.late"]["alert"] is True
    assert kpis["production.completed_month"]["value"] >= 1
