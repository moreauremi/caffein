# SPDX-License-Identifier: AGPL-3.0-or-later
"""Données techniques : articles, nomenclatures, gammes, coûts de revient, protection des fiches utilisées."""

import pytest

from caffein import db, services
from caffein.core import modules as registry
from caffein.modules.technical import services as technical

from .helpers import article_id, disable_module

BASE = "/api/data/technical"


@pytest.fixture()
def restore_modules():
    yield
    registry.enable_all()


def test_article_numbering_and_margin(client):
    res = client.post(f"{BASE}/articles", json={"name": "Carnet A5", "kind": "goods", "unit": "u", "sale_price": "12,50",
                                                "purchase_price": 5, "code": "PIRATE"})
    assert res.status_code == 201, res.text
    article = res.json()
    assert article["code"] == "ART-0010" and article["margin_rate"] == 60.0 and article["cost_price"] == 5
    assert article["active"] is True and article["vat_rate"] == 20
    assert client.post(f"{BASE}/articles", json={"name": "Conseil", "kind": "service", "min_stock": 3}).status_code == 400
    assert client.post(f"{BASE}/articles", json={"name": "X", "kind": "inconnu"}).status_code == 400
    assert client.post(f"{BASE}/articles", json={"name": "X", "vat_rate": 19}).status_code == 400
    listing = client.get(f"{BASE}/articles?f_kind=raw").json()
    assert listing["total"] == 4 and all(r["kind"] == "raw" for r in listing["rows"])


def test_bom_cost_and_cycles(client):
    paper, kit, cards = (article_id(n) for n in ("Papier couché 350 g, feuille SRA3", "Kit papeterie de marque",
                                                 "Jeu de cartes de visite (100 ex.)"))
    product = client.post(f"{BASE}/articles", json={"name": "Bloc-notes", "kind": "finished"}).json()
    bom = client.post(f"{BASE}/boms", json={"article_id": product["id"], "quantity": 2, "lines": [
        {"article_id": paper, "quantity": 10, "scrap_rate": 10}]})
    assert bom.status_code == 201, bom.text
    # 10 feuilles × 1,10 (pertes) × 0,42 € = 4,62 € pour 2 blocs → 2,31 € par bloc
    assert bom.json()["unit_cost"] == 2.31 and bom.json()["lines"][0]["line_cost"] == 4.62
    assert technical.components_for(product["id"], 4) == [{"article_id": paper, "quantity": 22.0}]
    assert client.get(f"{BASE}/articles/{product['id']}").json()["cost_price"] == 2.31
    # un article n'est pas son propre composant, même indirectement
    self_bom = client.post(f"{BASE}/boms", json={"article_id": paper, "lines": [{"article_id": paper, "quantity": 1}]})
    assert self_bom.status_code == 400
    loop = client.post(f"{BASE}/boms", json={"article_id": cards, "lines": [{"article_id": kit, "quantity": 1}]})
    assert loop.status_code == 400 and "circulaire" in loop.json()["detail"]
    assert client.post(f"{BASE}/boms", json={"article_id": product["id"], "quantity": 0}).status_code == 400
    preview = client.post(f"{BASE}/boms/preview", json={"quantity": 1, "lines": [{"article_id": paper, "quantity": 100}]}).json()
    assert preview["computed"]["unit_cost"] == 42 and preview["children"]["lines"][0]["line_cost"] == 42


def test_cost_rolls_up_through_bills_and_routings(demo):
    kit = article_id("Kit papeterie de marque")
    cards = article_id("Jeu de cartes de visite (100 ex.)")
    # cartes : matière 5 × 1,04 × 0,42 = 2,184 ; gamme 4 min à 45 €/h + 3 min à 30 €/h = 4,50
    assert technical.cost_price(cards) == pytest.approx(6.684)
    assert technical.active_routing(kit)["steps"][0]["workcenter"] == "Imprimante numérique"
    assert technical.cost_price(kit) == pytest.approx(17.31 + 18.6667, abs=0.01)


def test_used_records_cannot_be_deleted(client):
    paper = article_id("Papier couché 350 g, feuille SRA3")
    res = client.delete(f"{BASE}/articles/{paper}")
    assert res.status_code == 409 and "nomenclatures" in res.json()["detail"]
    service = article_id("Heure de conception graphique")
    client.post("/api/invoices", json={"kind": "invoice", "client_id": services.list_clients()[0]["id"],
                                       "items": [{"description": "Conception", "quantity": 2, "unit_price": 65, "article_id": service}]})
    res = client.delete(f"{BASE}/articles/{service}")
    assert res.status_code == 409 and "factures" in res.json()["detail"]
    family = db.fetch_one("SELECT id FROM technical_families WHERE name = 'Prestations'")["id"]
    assert client.delete(f"{BASE}/families/{family}").status_code == 409
    spare = client.post(f"{BASE}/articles", json={"name": "Article sans usage"}).json()
    assert client.delete(f"{BASE}/articles/{spare['id']}").status_code == 204


def test_routing_totals(client):
    center = client.post(f"{BASE}/workcenters", json={"name": "Presse", "hourly_cost": 60, "capacity_hours": 8}).json()
    assert center["code"].startswith("PC-")
    product = client.post(f"{BASE}/articles", json={"name": "Badge", "kind": "finished"}).json()
    routing = client.post(f"{BASE}/routings", json={"article_id": product["id"], "steps": [
        {"workcenter_id": center["id"], "description": "Pressage", "setup_minutes": 30, "run_minutes": 1.5}]}).json()
    assert routing["unit_cost"] == 1.5 and routing["run_minutes_total"] == 1.5 and routing["setup_minutes_total"] == 30
    assert routing["steps"][0]["step_cost"] == 1.5
    assert client.post(f"{BASE}/routings", json={"article_id": product["id"], "steps": [{"description": "x"}]}).status_code == 400


def test_order_lines_pick_article_values(client):
    kakemono = article_id("Kakémono 85×200 cm")
    # depuis une ligne de commande, chaque choix porte les valeurs à recopier
    options = client.get("/api/data/technical/articles/options", params={"q": "kakémono", "for": "sales.orders.article_id"}).json()
    assert options[0]["id"] == kakemono and options[0]["fill"] == {"description": "Kakémono 85×200 cm", "unit_price": 129}
    options = client.get("/api/data/technical/articles/options", params={"q": "kakémono", "for": "sales.orders.lines"}).json()
    assert options[0]["id"] == kakemono and "fill" not in options[0]  # champ inconnu : rien à recopier
    # le serveur recopie la désignation et le prix de l'article quand la ligne les laisse vides
    order = client.post("/api/data/sales/orders", json={"client_id": services.list_clients()[0]["id"], "lines": [
        {"article_id": kakemono, "quantity": 2}]}).json()
    assert order["lines"][0]["description"] == "Kakémono 85×200 cm" and order["lines"][0]["unit_price"] == 129
    assert order["total_ht"] == 258


def test_reference_fill_options(client):
    from caffein.core import entities

    field = next(f for f in entities.get("sales.orders").children[0].fields if f.name == "article_id")
    rows = entities.options(entities.get("technical.articles"), "Kit", fill=field.fill)
    assert rows[0]["fill"] == {"description": "Kit papeterie de marque", "unit_price": 290}


def test_disabling_technical_hides_article_fields(client, restore_modules):
    assert client.put("/api/settings/modules/technical", json={"enabled": False}).status_code == 409  # la Logistique en dépend
    disable_module(client, "technical")
    meta = client.get("/api/meta").json()
    lines = meta["entities"]["sales.orders"]["children"][0]["fields"]
    assert "article_id" not in [f["name"] for f in lines]
    assert client.get(f"{BASE}/articles").status_code == 404
    order = client.post("/api/data/sales/orders", json={"client_id": services.list_clients()[0]["id"], "lines": [
        {"description": "Sans article", "quantity": 1, "unit_price": 10, "article_id": 1}]})
    assert order.status_code == 201 and order.json()["lines"][0].get("article_id") is None
