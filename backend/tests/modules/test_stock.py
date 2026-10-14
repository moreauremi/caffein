# SPDX-License-Identifier: AGPL-3.0-or-later
"""Logistique : mouvements (registre définitif), niveaux, réapprovisionnement, réactions aux autres modules."""

import pytest

from caffein import db, services
from caffein.core import events
from caffein.core import modules as registry
from caffein.modules.stock import services as stock

from .helpers import article_id, disable_module

BASE = "/api/data/stock"


@pytest.fixture()
def restore_modules():
    yield
    registry.enable_all()


def _status(client, name):
    rows = client.get(f"{BASE}/stock", params={"q": name}).json()["rows"]
    return next(r for r in rows if r["article_name"] == name)


def test_manual_movements_follow_their_kind(client):
    envelope = article_id("Enveloppe kraft C5")
    before = stock.on_hand(envelope)
    receipt = client.post(f"{BASE}/movements", json={"kind": "receipt", "article_id": envelope, "quantity": "-100",
                                                     "reference": "BL 778"})
    assert receipt.status_code == 201, receipt.text
    assert receipt.json()["quantity"] == 100 and receipt.json()["warehouse_id__label"] == "Entrepôt principal"
    issue = client.post(f"{BASE}/movements", json={"kind": "delivery", "article_id": envelope, "quantity": 30}).json()
    assert issue["quantity"] == -30 and issue["code"].startswith("MVT-")
    adjust = client.post(f"{BASE}/movements", json={"kind": "adjustment", "article_id": envelope, "quantity": -5}).json()
    assert adjust["quantity"] == -5
    assert stock.on_hand(envelope) == before + 65
    # registre définitif : ni modification ni suppression
    assert client.put(f"{BASE}/movements/{issue['id']}", json={"quantity": 1}).status_code == 409
    assert client.delete(f"{BASE}/movements/{issue['id']}").status_code == 409
    for bad in ({"kind": "production", "article_id": envelope, "quantity": 1}, {"kind": "receipt", "article_id": envelope, "quantity": 0},
                {"kind": "receipt", "article_id": article_id("Heure de conception graphique"), "quantity": 1},
                {"kind": "receipt", "quantity": 1}):
        assert client.post(f"{BASE}/movements", json=bad).status_code == 400, bad


def test_stock_status_and_reorder(client):
    boxes = _status(client, "Boîte cadeau kraft 22×16 cm")
    assert boxes["quantity"] == 32 and boxes["status"] == "reorder" and boxes["to_order"] == 100
    assert boxes["value"] == round(32 * 1.35, 2)
    kit = _status(client, "Kit papeterie de marque")
    assert kit["status"] == "ok" and kit["to_order"] is None and kit["value"] > 0
    reorder = client.get(f"{BASE}/stock?f_status=reorder").json()
    assert {r["article_name"] for r in reorder["rows"]} == {"Boîte cadeau kraft 22×16 cm", "Papier de soie (feuille)",
                                                             "Kakémono 85×200 cm"}
    assert "Heure de conception graphique" not in [r["article_name"] for r in client.get(f"{BASE}/stock?size=200").json()["rows"]]
    assert client.post(f"{BASE}/stock", json={}).status_code == 409  # vue : consultation seulement
    kpis = {k["key"]: k for k in client.get("/api/home").json()["kpis"]}
    assert kpis["stock.to_reorder"]["value"] == 3 and kpis["stock.to_reorder"]["alert"] is True
    assert kpis["stock.stock_value"]["value"] > 0


def test_sales_delivery_moves_stock_once(client):
    kit, service = article_id("Kit papeterie de marque"), article_id("Heure de conception graphique")
    before = stock.on_hand(kit)
    order = client.post("/api/data/sales/orders", json={"client_id": services.list_clients()[0]["id"], "lines": [
        {"article_id": kit, "quantity": 2}, {"article_id": service, "quantity": 3}, {"description": "Port", "quantity": 1}]}).json()
    client.post(f"/api/data/sales/orders/{order['id']}/actions/confirm")
    delivered = client.post(f"/api/data/sales/orders/{order['id']}/actions/deliver").json()
    assert "1 mouvement" in delivered["message"]
    assert stock.on_hand(kit) == before - 2
    move = db.fetch_one("SELECT * FROM stock_movements WHERE source = ?", (f"sales.orders:{order['id']}",))
    assert move["kind"] == "delivery" and move["reference"] == order["code"]
    # le même document n'est jamais compté deux fois
    payload = {"order_id": order["id"], "code": order["code"], "lines": [{"article_id": kit, "quantity": 2}]}
    assert stock.on_sales_delivered(payload) is None and stock.on_hand(kit) == before - 2


def test_purchase_and_production_events(demo):
    paper, kit, boxes = (article_id(n) for n in ("Papier couché 350 g, feuille SRA3", "Kit papeterie de marque",
                                                 "Boîte cadeau kraft 22×16 cm"))
    before = {a: stock.on_hand(a) for a in (paper, kit, boxes)}
    messages = events.emit("purchases.order_received", {"order_id": 7, "code": "CF-2026-0007", "date": "2026-10-01",
                                                        "lines": [{"article_id": boxes, "quantity": 100, "unit_price": 1.3}]})
    assert messages == ["Stock : 1 mouvement(s) enregistré(s)."]
    assert db.fetch_one("SELECT unit_cost FROM stock_movements WHERE source = 'purchases.orders:7'")["unit_cost"] == 1.3
    events.emit("production.order_completed", {"order_id": 3, "code": "OF-2026-0003", "article_id": kit, "quantity": 4,
                                               "components": [{"article_id": paper, "quantity": 41.2}, {"article_id": boxes, "quantity": 4}]})
    assert stock.on_hand(kit) == before[kit] + 4
    assert stock.on_hand(paper) == pytest.approx(before[paper] - 41.2)
    assert stock.on_hand(boxes) == before[boxes] + 100 - 4
    kinds = {r["kind"] for r in db.fetch_all("SELECT kind FROM stock_movements WHERE source = 'production.orders:3'")}
    assert kinds == {"production", "consumption"}


def test_disabled_logistics_ignores_deliveries(client, restore_modules):
    kit = article_id("Kit papeterie de marque")
    before = stock.on_hand(kit)
    disable_module(client, "stock")
    order = client.post("/api/data/sales/orders", json={"client_id": services.list_clients()[0]["id"], "lines": [
        {"article_id": kit, "quantity": 1}]}).json()
    client.post(f"/api/data/sales/orders/{order['id']}/actions/confirm")
    delivered = client.post(f"/api/data/sales/orders/{order['id']}/actions/deliver").json()
    assert delivered["row"]["status"] == "delivered" and "mouvement" not in delivered["message"]
    assert stock.on_hand(kit) == before
    assert client.get(f"{BASE}/stock").status_code == 404


def test_warehouses(client):
    second = client.post(f"{BASE}/warehouses", json={"name": "Dépôt Villeurbanne", "is_default": True}).json()
    rows = client.get(f"{BASE}/warehouses").json()["rows"]
    assert [r["name"] for r in rows if r["is_default"]] == ["Dépôt Villeurbanne"]
    assert stock.default_warehouse_id() == second["id"]
    main = next(r for r in rows if r["name"] == "Entrepôt principal")
    res = client.delete(f"{BASE}/warehouses/{main['id']}")
    assert res.status_code == 409 and "mouvements" in res.json()["detail"]
    assert client.post(f"{BASE}/warehouses", json={"name": "dépôt villeurbanne"}).status_code == 400  # nom déjà pris
    levels = client.get(f"{BASE}/levels", params={"f_warehouse_id": main["id"]}).json()
    assert levels["total"] >= 8 and levels["rows"][0]["warehouse_id__label"] == "Entrepôt principal"
