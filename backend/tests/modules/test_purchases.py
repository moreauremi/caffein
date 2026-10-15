# SPDX-License-Identifier: AGPL-3.0-or-later
"""Achats : fournisseurs, commandes fournisseurs (montants, envoi, réception, annulation), entrée en stock,
droits, chiffres clés et données de démonstration."""

import csv
import io
from datetime import timedelta

import pytest

from caffein import dashboard, db
from caffein.core import modules as registry
from caffein.core.errors import Conflict
from caffein.modules.purchases.entities import ORDERS
from caffein.modules.stock import services as stock
from caffein.utils import today

from .helpers import article_id, disable_module, login_as, make_member

BASE = "/api/data/purchases"
PAPER = "Papier couché 350 g, feuille SRA3"
DEMO_SUPPLIERS = {"Papeterie Lyonnaise", "Emballages du Rhône", "Imprimerie du Rhône"}


@pytest.fixture()
def restore_modules():
    yield
    registry.enable_all()


def _day(offset: int = 0) -> str:
    return (today() + timedelta(days=offset)).isoformat()


def _supplier(client, name: str = "Cartonnages Rhodaniens", **extra) -> dict:
    res = client.post(f"{BASE}/suppliers", json={"name": name, **extra})
    assert res.status_code == 201, res.text
    return res.json()


def _order(client, supplier: dict, lines: list[dict], **extra) -> dict:
    res = client.post(f"{BASE}/orders", json={"supplier_id": supplier["id"], "lines": lines, **extra})
    assert res.status_code == 201, res.text
    return res.json()


def _act(client, order: dict, action: str, **payload):
    return client.post(f"{BASE}/orders/{order['id']}/actions/{action}", json=payload)


def _article(article: int) -> dict:
    return db.fetch_one("SELECT name, purchase_price FROM technical_articles WHERE id = ?", (article,))


def _moves(order: dict) -> list[dict]:
    return db.fetch_all("SELECT * FROM stock_movements WHERE source = ? ORDER BY id", (f"purchases.orders:{order['id']}",))


def _error(res, status: int = 400) -> str:
    assert res.status_code == status, res.text
    return res.json()["detail"]


# ═════════════════════════════════════════════════════════════════════════
# Fournisseurs
# ═════════════════════════════════════════════════════════════════════════
def test_supplier_numbering_and_validation(client):
    count = db.fetch_one("SELECT COUNT(*) AS n FROM purchases_suppliers")["n"]
    supplier = _supplier(client, code="PIRATE", siren="123 456 789", vat_number="fr 12 123456789",
                         email="contact@cartonnages.example", city="Vénissieux", orders_count=99)
    assert supplier["code"] == f"FRN-{count + 1:04d}"
    assert supplier["country"] == "France" and supplier["payment_terms_days"] == 30 and supplier["active"] is True
    assert supplier["siren"] == "123456789" and supplier["vat_number"] == "FR12123456789"
    assert supplier["orders_count"] == 0 and supplier["ordered_ytd"] == 0
    assert _supplier(client, "Second fournisseur")["code"] == f"FRN-{count + 2:04d}"
    edited = client.put(f"{BASE}/suppliers/{supplier['id']}", json={"payment_terms_days": 60, "code": "X"}).json()
    assert edited["payment_terms_days"] == 60 and edited["code"] == supplier["code"] and edited["city"] == "Vénissieux"
    found = client.get(f"{BASE}/suppliers", params={"q": "nissieux"}).json()
    assert [r["id"] for r in found["rows"]] == [supplier["id"]]
    # choix d'un fournisseur dans une commande : nom et ville
    options = client.get(f"{BASE}/suppliers/options", params={"q": "cartonnages"}).json()
    assert [(o["id"], o["label"], o["sublabel"]) for o in options] == [(supplier["id"], "Cartonnages Rhodaniens", "Vénissieux")]
    for bad, message in (
        ({}, "Nom : obligatoire."),
        ({"name": "  "}, "Nom : obligatoire."),
        ({"name": "cartonnages rhodaniens"}, "Nom : « cartonnages rhodaniens » existe déjà."),
        ({"name": "A", "payment_terms_days": 121}, "Délai de paiement (jours) : 120 au maximum."),
        ({"name": "A", "payment_terms_days": -1}, "Délai de paiement (jours) : 0 au minimum."),
        ({"name": "A", "payment_terms_days": 2.5}, "Délai de paiement (jours) : nombre entier attendu."),
        ({"name": "A", "payment_terms_days": 10**20}, "Délai de paiement (jours) : nombre hors limites."),
        ({"name": "A", "email": "pas-un-email"}, "Email : adresse email invalide."),
        ({"name": "A", "phone": "appelez-moi"}, "Téléphone : numéro invalide."),
        ({"name": "A", "siren": "123 456 78"}, "SIREN : 9 chiffres attendus."),
        ({"name": "A", "siren": "123 456 789 00010"}, "SIREN : 9 chiffres attendus."),
        ({"name": "A", "active": "peut-être"}, "Actif : oui ou non attendu."),
    ):
        assert _error(client.post(f"{BASE}/suppliers", json=bad)) == message, bad
    assert client.put(f"{BASE}/suppliers/{supplier['id']}", json={"name": "Second fournisseur"}).status_code == 400


def test_supplier_figures_and_deletion(client):
    supplier = _supplier(client)
    carton = [{"description": "Carton double cannelure", "quantity": 10, "unit_price": 2.5}]  # 25,00 € HT
    sent = _order(client, supplier, carton)
    _act(client, sent, "send")
    received = _order(client, supplier, [{"description": "Ruban adhésif", "quantity": 4, "unit_price": 3.15}])  # 12,60 € HT
    _act(client, received, "send")
    _act(client, received, "receive")
    _order(client, supplier, carton)                                     # brouillon : compté, pas commandé
    _act(client, _order(client, supplier, carton), "cancel")            # annulée : ni comptée, ni commandée
    last_year = _order(client, supplier, carton, order_date=f"{today().year - 1}-12-31")
    _act(client, last_year, "send")                                      # l'an dernier : comptée, hors montant de l'année
    record = client.get(f"{BASE}/suppliers/{supplier['id']}").json()
    assert record["orders_count"] == 4 and record["ordered_ytd"] == 37.6
    listed = client.get(f"{BASE}/suppliers", params={"q": supplier["name"]}).json()["rows"]
    assert [(r["orders_count"], r["ordered_ytd"]) for r in listed] == [(4, 37.6)]
    # les commandes d'un fournisseur : filtre de la liste
    mine = client.get(f"{BASE}/orders", params={"f_supplier_id": supplier["id"]}).json()
    assert mine["total"] == 5 and {r["supplier_id"] for r in mine["rows"]} == {supplier["id"]}
    assert client.get(f"{BASE}/orders", params={"f_supplier_id": 10**20}).status_code == 400
    # un fournisseur qui a des commandes ne se supprime pas ; sans commande, si
    res = client.delete(f"{BASE}/suppliers/{supplier['id']}")
    assert _error(res, 409) == "Suppression impossible : cette fiche est utilisée ailleurs (commandes fournisseurs : 5)."
    spare = _supplier(client, "Fournisseur sans commande")
    assert client.delete(f"{BASE}/suppliers/{spare['id']}").status_code == 204
    assert client.get(f"{BASE}/suppliers/{spare['id']}").status_code == 404


def test_inactive_supplier_gets_no_new_order(client):
    supplier = _supplier(client)
    draft = _order(client, supplier, [{"description": "Carton", "quantity": 1, "unit_price": 1}])
    client.put(f"{BASE}/suppliers/{supplier['id']}", json={"active": False})
    res = client.post(f"{BASE}/orders", json={"supplier_id": supplier["id"]})
    assert _error(res) == "Fournisseur : ce fournisseur est inactif ; réactivez-le dans sa fiche pour lui passer commande."
    other = _order(client, _supplier(client, "Autre fournisseur"), [])
    assert client.put(f"{BASE}/orders/{other['id']}", json={"supplier_id": supplier["id"]}).status_code == 400
    # un brouillon déjà préparé chez lui reste modifiable, mais ne part pas tant que le fournisseur est inactif
    assert client.put(f"{BASE}/orders/{draft['id']}", json={"notes": "Livrer à l'atelier"}).status_code == 200
    assert _error(_act(client, draft, "send")) == ("Fournisseur : ce fournisseur est inactif ; réactivez-le dans sa fiche "
                                                    "pour lui envoyer la commande.")
    inactive = client.get(f"{BASE}/suppliers", params={"f_active": "0"}).json()["rows"]
    assert [r["id"] for r in inactive] == [supplier["id"]]
    client.put(f"{BASE}/suppliers/{supplier['id']}", json={"active": True})
    assert _act(client, draft, "send").json()["row"]["status"] == "sent"


# ═════════════════════════════════════════════════════════════════════════
# Commandes : montants, saisie, validation
# ═════════════════════════════════════════════════════════════════════════
MIXED_LINES = [
    {"description": "Papier kraft", "quantity": 3, "unit_price": 12.5, "vat_rate": 20},       # 37,50 HT, TVA 7,50
    {"description": "Livres techniques", "quantity": 7, "unit_price": 1.15, "vat_rate": 5.5},  # 8,05 HT, TVA 0,44
    {"description": "Traiteur", "quantity": 1, "unit_price": 99.99, "vat_rate": 10},          # 99,99 HT, TVA 10,00
    {"description": "Presse", "quantity": 10, "unit_price": "0,333", "vat_rate": 2.1},        # 0,33 → 3,30 HT, TVA 0,07
    {"description": "Formation", "quantity": 2, "unit_price": 45, "vat_rate": 0},              # 90,00 HT, sans TVA
]


def test_order_totals_with_mixed_vat(client):
    count = db.fetch_one("SELECT COUNT(*) AS n FROM purchases_orders")["n"]
    order = _order(client, _supplier(client), MIXED_LINES, code="PIRATE", status="received", received_date=_day(),
                   total_ht=1, late=True)
    assert order["code"] == f"CF-{today().year}-{count + 1:04d}" and order["status"] == "draft"
    assert order["received_date"] is None
    assert order["order_date"] == _day() and order["supplier_id__label"] == "Cartonnages Rhodaniens"
    assert [line["amount"] for line in order["lines"]] == [37.5, 8.05, 99.99, 3.3, 90]
    assert [line["unit_price"] for line in order["lines"]][3] == 0.33
    assert (order["total_ht"], order["total_vat"], order["total_ttc"]) == (238.84, 18.01, 256.85)
    assert order["late"] is False and order["_locked"] is None and set(order["_actions"]) == {"send", "cancel"}
    # la liste calcule les mêmes montants, par une requête groupée
    listed = next(r for r in client.get(f"{BASE}/orders").json()["rows"] if r["id"] == order["id"])
    assert (listed["total_ht"], listed["total_vat"], listed["total_ttc"]) == (238.84, 18.01, 256.85)
    # aperçu pendant la saisie : le serveur calcule, rien n'est enregistré
    preview = client.post(f"{BASE}/orders/preview", json={"lines": MIXED_LINES}).json()
    assert preview["computed"] == {"total_ht": 238.84, "total_vat": 18.01, "total_ttc": 256.85, "late": False}
    assert [line["amount"] for line in preview["children"]["lines"]] == [37.5, 8.05, 99.99, 3.3, 90]
    # TVA arrondie ligne par ligne : 3 × 0,0055 € → 3 × 0,01 €
    small = [{"description": "Timbre", "quantity": 1, "unit_price": 0.1, "vat_rate": 5.5}] * 3
    assert client.post(f"{BASE}/orders/preview", json={"lines": small}).json()["computed"]["total_vat"] == 0.03
    # aperçu d'une saisie incomplète ou erronée : valeurs par défaut, valeurs invalides comptées pour zéro
    partial = client.post(f"{BASE}/orders/preview", json={"lines": [{"unit_price": 10}, {"quantity": "x", "unit_price": 5}]})
    assert partial.json()["computed"] == {"total_ht": 10, "total_vat": 2, "total_ttc": 12, "late": False}
    assert db.fetch_one("SELECT COUNT(*) AS n FROM purchases_orders")["n"] == count + 1
    # modification d'un brouillon : les lignes sont remplacées, le numéro reste
    edited = client.put(f"{BASE}/orders/{order['id']}", json={"lines": MIXED_LINES[:1], "code": "X"}).json()
    assert edited["code"] == order["code"] and (edited["total_ht"], edited["total_vat"], edited["total_ttc"]) == (37.5, 7.5, 45)
    assert db.fetch_one("SELECT COUNT(*) AS n FROM purchases_order_lines WHERE order_id = ?", (order["id"],))["n"] == 1
    empty = _order(client, _supplier(client, "Autre"), [])
    assert empty["code"] == f"CF-{today().year}-{count + 2:04d}"
    assert (empty["total_ht"], empty["total_vat"], empty["total_ttc"]) == (0, 0, 0)


def test_order_validation(client):
    supplier = _supplier(client)

    def post(data):
        return client.post(f"{BASE}/orders", json={"supplier_id": supplier["id"], **data})

    line = {"description": "Carton", "quantity": 1, "unit_price": 1}
    cases = (
        ({"supplier_id": None}, "Fournisseur : obligatoire."),
        ({"supplier_id": 999999}, "Fournisseur : fiche introuvable."),
        ({"supplier_id": 10**20}, "Fournisseur : nombre hors limites."),
        ({"lines": "Carton"}, "Lignes : liste attendue."),
        ({"lines": [{"quantity": 1}]}, "Lignes, ligne 1 — Désignation : obligatoire."),
        ({"lines": [line, {**line, "quantity": 0}]}, "Lignes, ligne 2 — Quantité : elle doit être positive."),
        ({"lines": [{**line, "quantity": -3}]}, "Lignes, ligne 1 — Quantité : elle doit être positive."),
        ({"lines": [{**line, "quantity": None}]}, "Lignes, ligne 1 — Quantité : obligatoire."),
        ({"lines": [{**line, "quantity": "beaucoup"}]}, "Lignes, ligne 1 — Quantité : nombre attendu."),
        ({"lines": [{**line, "unit_price": -1}]}, "Lignes, ligne 1 — Prix unitaire HT : 0 au minimum."),
        ({"lines": [{**line, "unit_price": None}]}, "Lignes, ligne 1 — Prix unitaire HT : obligatoire."),
        ({"lines": [{**line, "vat_rate": 19}]}, "Lignes, ligne 1 — TVA : valeur non proposée."),
        ({"lines": [{**line, "vat_rate": None}]}, "Lignes, ligne 1 — TVA : obligatoire."),
        ({"lines": [{**line, "article_id": 999999}]}, "Lignes, ligne 1 — Article : fiche introuvable."),
        ({"order_date": _day(), "expected_date": _day(-1)}, "Livraison prévue : elle ne peut pas précéder la date de commande."),
        ({"expected_date": "31/02/2026"}, "Livraison prévue : date invalide."),
        ({"warehouse_id": 999999}, "Entrepôt de réception : fiche introuvable."),
    )
    for data, message in cases:
        assert _error(post(data)) == message, data
    # valeurs par défaut d'une ligne : quantité 1, prix 0, TVA 20 %
    order = post({"lines": [{"description": "Échantillon"}]}).json()
    assert {k: order["lines"][0][k] for k in ("quantity", "unit_price", "vat_rate", "amount")} == \
        {"quantity": 1, "unit_price": 0, "vat_rate": 20, "amount": 0}
    # la livraison prévue peut tomber le jour de la commande
    assert post({"order_date": _day(-3), "expected_date": _day(-3)}).status_code == 201


def test_lines_take_the_article_purchase_price(client):
    paper, envelope, kit = (article_id(n) for n in (PAPER, "Enveloppe kraft C5", "Kit papeterie de marque"))
    paper_row, envelope_row = _article(paper), _article(envelope)
    assert paper_row["purchase_price"] and _article(kit)["purchase_price"] is None  # le kit est fabriqué
    # depuis le formulaire, chaque article proposé porte la désignation et le coût d'achat à recopier
    options = client.get("/api/data/technical/articles/options", params={"q": "kraft C5", "for": "purchases.orders.article_id"})
    assert options.json()[0]["fill"] == {"description": "Enveloppe kraft C5", "unit_price": envelope_row["purchase_price"]}
    order = _order(client, _supplier(client), [
        {"article_id": paper, "quantity": 500},                                                  # tout vient de l'article
        {"article_id": envelope, "quantity": 100, "description": "Enveloppes C5, lot promo", "unit_price": 0.15},
        {"article_id": paper, "quantity": 10, "description": "", "unit_price": ""},               # vides : recopiés
        {"article_id": kit, "quantity": 1},                                                      # sans coût d'achat
        {"article_id": envelope, "quantity": 2, "unit_price": 0},                                # gratuit : 0 est gardé
    ])
    lines = order["lines"]
    assert (lines[0]["description"], lines[0]["unit_price"]) == (paper_row["name"], paper_row["purchase_price"])
    assert lines[0]["amount"] == round(500 * paper_row["purchase_price"], 2) and lines[0]["article_id__label"] == paper_row["name"]
    assert (lines[1]["description"], lines[1]["unit_price"]) == ("Enveloppes C5, lot promo", 0.15)
    assert (lines[2]["description"], lines[2]["unit_price"]) == (paper_row["name"], paper_row["purchase_price"])
    assert (lines[3]["description"], lines[3]["unit_price"]) == ("Kit papeterie de marque", 0)
    assert (lines[4]["description"], lines[4]["unit_price"]) == ("Enveloppe kraft C5", 0)
    assert order["total_ht"] == round(510 * paper_row["purchase_price"] + 15, 2)
    # un article commandé ne se supprime plus
    article = client.post("/api/data/technical/articles", json={"name": "Ruban satin", "purchase_price": 4.2}).json()
    _order(client, _supplier(client, "Mercerie Croix-Rousse"), [{"article_id": article["id"], "quantity": 3}])
    res = client.delete(f"/api/data/technical/articles/{article['id']}")
    assert _error(res, 409) == "Suppression impossible : cette fiche est utilisée ailleurs (commandes fournisseurs : 1)."


def test_free_text_lines_without_technical_data(client, restore_modules):
    disable_module(client, "technical")  # la Logistique et la Production, qui en dépendent, d'abord
    meta = client.get("/api/meta").json()["entities"]["purchases.orders"]
    [lines] = meta["children"]
    assert [f["name"] for f in lines["fields"]] == ["description", "quantity", "unit_price", "vat_rate", "amount"]
    assert "warehouse_id" not in [f["name"] for f in meta["fields"]]
    order = _order(client, _supplier(client), [{"article_id": article_id(PAPER), "description": "Cartons de déménagement",
                                                "quantity": 20, "unit_price": 1.5}])
    assert order["total_ht"] == 30 and "article_id" not in order["lines"][0]
    assert db.fetch_one("SELECT article_id FROM purchases_order_lines WHERE order_id = ?", (order["id"],))["article_id"] is None
    _act(client, order, "send")
    received = _act(client, order, "receive").json()
    assert received["row"]["status"] == "received" and received["message"] == f"Commande {order['code']} réceptionnée."


# ═════════════════════════════════════════════════════════════════════════
# Envoi, réception, annulation
# ═════════════════════════════════════════════════════════════════════════
def test_send_receive_cancel_workflow(client):
    supplier = _supplier(client)
    order = _order(client, supplier, [], order_date=None)
    assert order["order_date"] is None
    assert _error(_act(client, order, "send")) == "Lignes : ajoutez au moins une ligne avant d'envoyer la commande."
    assert _act(client, order, "receive").status_code == 409                       # brouillon → reçue : interdit
    client.put(f"{BASE}/orders/{order['id']}", json={"lines": [{"description": "Carton", "quantity": 20, "unit_price": 1.2}]})

    sent = _act(client, order, "send").json()
    row = sent["row"]
    assert sent["message"] == f"Commande {order['code']} envoyée."
    assert row["status"] == "sent" and row["order_date"] == _day() and row["received_date"] is None
    assert row["_locked"] == "Commande envoyée : elle ne se modifie plus. Annulez-la et créez-en une autre si besoin."
    assert set(row["_actions"]) == {"receive", "cancel"}
    assert _error(client.put(f"{BASE}/orders/{order['id']}", json={"notes": "x"}), 409) == row["_locked"]
    assert _error(_act(client, order, "send"), 409) == "Cette action n'est pas possible dans l'état actuel de la fiche."
    assert _error(client.delete(f"{BASE}/orders/{order['id']}"), 409) == row["_locked"]

    received = _act(client, order, "receive").json()
    assert received["message"] == f"Commande {order['code']} réceptionnée."   # sans article : aucun mouvement de stock
    assert received["row"]["status"] == "received" and received["row"]["received_date"] == _day()
    assert received["row"]["_actions"] == [] and received["row"]["_locked"] == "Commande reçue : elle ne se modifie plus."
    for action in ("receive", "cancel", "send"):
        assert _act(client, order, action).status_code == 409, action
    assert client.put(f"{BASE}/orders/{order['id']}", json={"lines": []}).status_code == 409
    assert client.delete(f"{BASE}/orders/{order['id']}").status_code == 409

    # brouillon annulé : plus aucune action
    draft = _order(client, supplier, [{"description": "Carton", "quantity": 1, "unit_price": 1}])
    cancelled = _act(client, draft, "cancel").json()
    assert cancelled["message"] == f"Commande {draft['code']} annulée."
    assert cancelled["row"]["status"] == "cancelled" and cancelled["row"]["_actions"] == []
    assert cancelled["row"]["_locked"] == "Commande annulée : elle ne se modifie plus."
    for action in ("send", "receive", "cancel"):
        assert _act(client, draft, action).status_code == 409, action
    assert client.put(f"{BASE}/orders/{draft['id']}", json={"notes": "x"}).status_code == 409
    # Le moteur refuse de supprimer une fiche verrouillée avant de consulter before_delete : une commande annulée
    # reste dans l'historique (demande d'évolution du socle transmise avec le module).
    assert client.delete(f"{BASE}/orders/{draft['id']}").status_code == 409

    # commande envoyée puis annulée : elle ne se réceptionne plus
    late = _order(client, supplier, [{"description": "Carton", "quantity": 1, "unit_price": 1}])
    _act(client, late, "send")
    assert _act(client, late, "cancel").json()["row"]["status"] == "cancelled"
    assert _act(client, late, "receive").status_code == 409

    # un brouillon se supprime, ses lignes avec lui
    spare = _order(client, supplier, [{"description": "Carton", "quantity": 1, "unit_price": 1}])
    assert client.delete(f"{BASE}/orders/{spare['id']}").status_code == 204
    assert db.fetch_one("SELECT COUNT(*) AS n FROM purchases_order_lines WHERE order_id = ?", (spare["id"],))["n"] == 0
    assert client.post(f"{BASE}/orders/{order['id']}/actions/inconnue").status_code == 404
    assert client.post(f"{BASE}/orders/999999/actions/send").status_code == 404


def test_deletion_and_lock_rules_by_status():
    ORDERS.before_delete({"status": "draft"})
    ORDERS.before_delete({"status": "cancelled"})
    for status in ("sent", "received"):
        with pytest.raises(Conflict, match="Seule une commande en brouillon ou annulée peut être supprimée."):
            ORDERS.before_delete({"status": status})
    assert ORDERS.locked({"status": "draft"}) is None
    assert all(ORDERS.locked({"status": status}) for status in ("sent", "received", "cancelled"))


def test_late_orders(client):
    supplier = _supplier(client)
    line = [{"description": "Carton", "quantity": 1, "unit_price": 1}]
    overdue = _order(client, supplier, line, order_date=_day(-10), expected_date=_day(-1))
    due_today = _order(client, supplier, line, order_date=_day(-10), expected_date=_day())
    undated = _order(client, supplier, line)
    draft = _order(client, supplier, line, order_date=_day(-10), expected_date=_day(-1))
    assert draft["late"] is False                                            # pas encore envoyée
    for order in (overdue, due_today, undated):
        _act(client, order, "send")
    rows = {r["id"]: r for r in client.get(f"{BASE}/orders", params={"f_status": "sent", "size": 200}).json()["rows"]}
    assert rows[overdue["id"]]["late"] is True and rows[due_today["id"]]["late"] is False and rows[undated["id"]]["late"] is False
    assert client.get(f"{BASE}/orders/{overdue['id']}").json()["late"] is True
    assert _act(client, overdue, "receive").json()["row"]["late"] is False   # reçue : plus en retard
    # sans date de commande, l'envoi la fixe au jour même : une livraison prévue déjà passée est refusée
    stale = _order(client, supplier, line, order_date=None, expected_date=_day(-2))
    assert _error(_act(client, stale, "send")) == "Livraison prévue : elle ne peut pas précéder la date de commande."
    client.put(f"{BASE}/orders/{stale['id']}", json={"expected_date": _day(5)})
    assert _act(client, stale, "send").json()["row"]["order_date"] == _day()


# ═════════════════════════════════════════════════════════════════════════
# Réception : entrée en stock (Logistique), événement
# ═════════════════════════════════════════════════════════════════════════
def test_receipt_enters_stock_at_purchase_price(client):
    paper, service = article_id(PAPER), article_id("Heure de conception graphique")
    before = stock.on_hand(paper)
    supplier = _supplier(client)
    order = _order(client, supplier, [
        {"article_id": paper, "quantity": 250, "unit_price": 0.39},
        {"article_id": service, "quantity": 2, "unit_price": 50},          # un service ne se stocke pas
        {"description": "Frais de port", "quantity": 1, "unit_price": 12},  # ligne libre
    ])
    _act(client, order, "send")
    assert stock.on_hand(paper) == before and not _moves(order)              # envoyée : rien n'est encore entré
    res = _act(client, order, "receive")
    assert res.status_code == 200, res.text
    assert res.json()["message"] == f"Commande {order['code']} réceptionnée. Stock : 1 mouvement(s) enregistré(s)."
    assert stock.on_hand(paper) == before + 250
    [move] = _moves(order)
    assert (move["kind"], move["quantity"], move["unit_cost"], move["article_id"]) == ("receipt", 250, 0.39, paper)
    assert move["reference"] == order["code"] and move["date"] == _day()
    assert move["warehouse_id"] == stock.default_warehouse_id()
    # une commande ne se réceptionne qu'une fois, et la Logistique ne la compte jamais deux fois
    assert _act(client, order, "receive").status_code == 409
    payload = {"order_id": order["id"], "code": order["code"], "lines": [{"article_id": paper, "quantity": 250, "unit_price": 0.39}]}
    assert stock.on_purchase_received(payload) is None
    assert stock.on_hand(paper) == before + 250 and len(_moves(order)) == 1

    # entrepôt de réception choisi sur la commande
    reserve = client.post("/api/data/stock/warehouses", json={"name": "Dépôt de Vénissieux"}).json()
    second = _order(client, supplier, [{"article_id": paper, "quantity": 40, "unit_price": 0.41}], warehouse_id=reserve["id"])
    assert second["warehouse_id__label"] == "Dépôt de Vénissieux"
    _act(client, second, "send")
    _act(client, second, "receive")
    assert stock.on_hand(paper, reserve["id"]) == 40 and stock.on_hand(paper) == before + 290
    assert [(m["warehouse_id"], m["unit_cost"]) for m in _moves(second)] == [(reserve["id"], 0.41)]
    # un entrepôt désigné par une commande ne se supprime pas
    res = client.delete(f"/api/data/stock/warehouses/{reserve['id']}")
    assert res.status_code == 409 and "commandes fournisseurs : 1" in res.json()["detail"]


def test_receipt_date_can_be_given(client):
    paper = article_id(PAPER)
    supplier = _supplier(client)
    order = _order(client, supplier, [{"article_id": paper, "quantity": 5, "unit_price": 0.4}], order_date=_day(-9))
    _act(client, order, "send")
    for bad, message in (({"date": _day(1)}, "Date de réception : elle ne peut pas être dans le futur."),
                         ({"date": _day(-10)}, "Date de réception : elle ne peut pas précéder la date de commande."),
                         ({"date": "hier"}, "Date de réception : date invalide."),
                         ({"date": 3}, "Date de réception : date invalide.")):
        assert _error(_act(client, order, "receive", **bad)) == message, bad
    assert client.get(f"{BASE}/orders/{order['id']}").json()["status"] == "sent" and not _moves(order)
    row = _act(client, order, "receive", date=_day(-2)).json()["row"]
    assert row["status"] == "received" and row["received_date"] == _day(-2)
    assert [m["date"] for m in _moves(order)] == [_day(-2)]


def test_receipt_event_payload(client, monkeypatch):
    seen = []

    def listener(payload):
        status = db.fetch_one("SELECT status FROM purchases_orders WHERE id = ?", (payload["order_id"],))["status"]
        seen.append((payload, status))
        return "Comptabilité prévenue."

    monkeypatch.setattr(registry.get("accounting"), "events", {"purchases.order_received": listener})
    paper = article_id(PAPER)
    reserve = client.post("/api/data/stock/warehouses", json={"name": "Dépôt de Vénissieux"}).json()
    order = _order(client, _supplier(client), [
        {"article_id": paper, "quantity": 12, "unit_price": 0.4, "vat_rate": 5.5},
        {"description": "Frais de port", "quantity": 1, "unit_price": 9.9},
    ], warehouse_id=reserve["id"])
    _act(client, order, "send")
    assert not seen                                           # l'envoi n'annonce rien
    res = _act(client, order, "receive").json()
    assert res["message"] == (f"Commande {order['code']} réceptionnée. Stock : 1 mouvement(s) enregistré(s). "
                              "Comptabilité prévenue.")
    [(payload, status)] = seen
    assert status == "sent"  # l'événement part avant que la réception soit enregistrée
    assert payload == {
        "order_id": order["id"], "code": order["code"], "date": _day(), "warehouse_id": reserve["id"],
        "lines": [{"article_id": paper, "description": _article(paper)["name"], "quantity": 12, "unit_price": 0.4},
                  {"article_id": None, "description": "Frais de port", "quantity": 1, "unit_price": 9.9}],
    }
    # sans entrepôt choisi : warehouse_id vaut None (la Logistique prend l'entrepôt par défaut)
    other = _order(client, _supplier(client, "Autre fournisseur"), [{"description": "Port", "quantity": 1, "unit_price": 5}])
    _act(client, other, "send")
    _act(client, other, "cancel")
    assert len(seen) == 1                                     # l'annulation n'annonce rien
    third = _order(client, _supplier(client, "Troisième fournisseur"), [{"description": "Port", "quantity": 1, "unit_price": 5}])
    _act(client, third, "send")
    _act(client, third, "receive")
    assert seen[1][0]["warehouse_id"] is None and seen[1][0]["lines"][0]["article_id"] is None


def test_subscriber_error_cancels_the_receipt(client, monkeypatch):
    def refuse(_payload):
        raise ValueError("Quai de réception fermé.")

    monkeypatch.setattr(registry.get("accounting"), "events", {"purchases.order_received": refuse})
    paper = article_id(PAPER)
    order = _order(client, _supplier(client), [{"article_id": paper, "quantity": 3, "unit_price": 0.4}])
    _act(client, order, "send")
    before = stock.on_hand(paper)
    assert _error(_act(client, order, "receive")) == "Quai de réception fermé."
    row = client.get(f"{BASE}/orders/{order['id']}").json()
    assert row["status"] == "sent" and row["received_date"] is None and set(row["_actions"]) == {"receive", "cancel"}
    # une fois l'abonné rétabli, la réception passe et le stock n'est compté qu'une fois
    monkeypatch.setattr(registry.get("accounting"), "events", {})
    assert _act(client, order, "receive").json()["row"]["status"] == "received"
    assert stock.on_hand(paper) == before + 3 and len(_moves(order)) == 1


def test_receive_without_logistics(client, restore_modules):
    paper = article_id(PAPER)
    before = stock.on_hand(paper)
    order = _order(client, _supplier(client), [{"article_id": paper, "quantity": 40, "unit_price": 0.4}])
    disable_module(client, "stock")
    fields = [f["name"] for f in client.get("/api/meta").json()["entities"]["purchases.orders"]["fields"]]
    assert "warehouse_id" not in fields and "supplier_id" in fields
    _act(client, order, "send")
    res = _act(client, order, "receive").json()
    assert res["row"]["status"] == "received" and res["message"] == f"Commande {order['code']} réceptionnée."
    assert stock.on_hand(paper) == before and not _moves(order)


# ═════════════════════════════════════════════════════════════════════════
# Droits, activation, description, chiffres clés, export
# ═════════════════════════════════════════════════════════════════════════
def test_readonly_role_cannot_write(client):
    supplier = _supplier(client)
    draft = _order(client, supplier, [{"description": "Carton", "quantity": 1, "unit_price": 1}])
    make_member("lecture-achats@test.local", "readonly")
    reader = login_as("lecture-achats@test.local")
    assert reader.get(f"{BASE}/orders").status_code == 200
    assert reader.get(f"{BASE}/orders/{draft['id']}").json()["_actions"] == []
    assert reader.get(f"{BASE}/orders/export").status_code == 200
    assert reader.post(f"{BASE}/orders", json={"supplier_id": supplier["id"]}).status_code == 403
    assert reader.put(f"{BASE}/orders/{draft['id']}", json={"notes": "x"}).status_code == 403
    assert reader.post(f"{BASE}/orders/preview", json={"lines": []}).status_code == 403
    for action in ("send", "cancel"):
        assert reader.post(f"{BASE}/orders/{draft['id']}/actions/{action}").status_code == 403
    assert reader.delete(f"{BASE}/orders/{draft['id']}").status_code == 403
    assert reader.post(f"{BASE}/suppliers", json={"name": "Lecture"}).status_code == 403
    assert reader.put(f"{BASE}/suppliers/{supplier['id']}", json={"city": "Lyon"}).status_code == 403
    assert reader.delete(f"{BASE}/suppliers/{supplier['id']}").status_code == 403
    meta = reader.get("/api/meta").json()["entities"]["purchases.orders"]
    assert not meta["can_create"] and not meta["can_edit"] and not meta["can_delete"]
    home = reader.get("/api/home").json()
    assert "purchases.to_receive" in {k["key"] for k in home["kpis"]}
    assert "purchases.new_order" not in {s["key"] for s in home["shortcuts"]}  # raccourci : niveau écriture
    assert client.get(f"{BASE}/orders/{draft['id']}").json()["status"] == "draft"


def test_buyer_role_runs_purchasing(client):
    paper = article_id(PAPER)
    make_member("acheteur@test.local", "buyer")
    buyer = login_as("acheteur@test.local")
    meta = buyer.get("/api/meta").json()
    keys = [m["key"] for m in meta["modules"]]
    assert "purchases" in keys and "sales" not in keys and meta["levels"]["purchases"] == 2
    orders = meta["entities"]["purchases.orders"]
    assert orders["can_create"] and orders["can_edit"] and not orders["can_delete"]
    supplier = buyer.post(f"{BASE}/suppliers", json={"name": "Fournisseur de l'acheteur"})
    assert supplier.status_code == 201
    options = buyer.get("/api/data/technical/articles/options", params={"q": "350 g", "for": "purchases.orders.article_id"})
    assert options.status_code == 200 and options.json()[0]["fill"]["unit_price"] == _article(paper)["purchase_price"]
    order = buyer.post(f"{BASE}/orders", json={"supplier_id": supplier.json()["id"], "lines": [{"article_id": paper, "quantity": 5}]})
    assert order.status_code == 201
    order = order.json()
    assert buyer.post(f"{BASE}/orders/{order['id']}/actions/send").status_code == 200
    received = buyer.post(f"{BASE}/orders/{order['id']}/actions/receive")
    assert received.status_code == 200 and "Stock : 1 mouvement(s)" in received.json()["message"]
    # suppression : niveau gestion, que l'acheteur n'a pas
    draft = buyer.post(f"{BASE}/orders", json={"supplier_id": supplier.json()["id"]}).json()
    assert buyer.delete(f"{BASE}/orders/{draft['id']}").status_code == 403
    assert buyer.delete(f"{BASE}/suppliers/{supplier.json()['id']}").status_code == 403
    assert buyer.post(f"{BASE}/orders/{draft['id']}/actions/cancel").status_code == 200
    home = buyer.get("/api/home").json()
    assert {"purchases.to_receive", "purchases.late_deliveries", "purchases.ordered_month"} <= {k["key"] for k in home["kpis"]}
    assert "purchases.new_order" in {s["key"] for s in home["shortcuts"]}
    # un commercial n'a pas accès aux achats ; une dérogation le lui donne
    seller = make_member("commercial@test.local", "sales")
    member = login_as("commercial@test.local")
    assert member.get(f"{BASE}/orders").status_code == 403
    assert "purchases.to_receive" not in {k["key"] for k in member.get("/api/home").json()["kpis"]}
    client.put(f"/api/users/{seller['id']}/permissions", json={"overrides": {"purchases": "write"}})
    assert member.post(f"{BASE}/orders", json={"supplier_id": supplier.json()["id"]}).status_code == 201


def test_disabled_purchases_disappear(client, restore_modules):
    article = client.post("/api/data/technical/articles", json={"name": "Ruban satin"}).json()
    order = _order(client, _supplier(client), [{"article_id": article["id"], "quantity": 1}])
    disable_module(client, "purchases")
    assert client.get(f"{BASE}/orders").status_code == 404
    assert client.get(f"{BASE}/orders/{order['id']}").status_code == 404
    assert client.post(f"{BASE}/suppliers", json={"name": "X"}).status_code == 404
    assert client.post(f"{BASE}/orders/{order['id']}/actions/send").status_code == 404
    meta = client.get("/api/meta").json()
    assert "purchases" not in [m["key"] for m in meta["modules"]] and "purchases.orders" not in meta["entities"]
    home = client.get("/api/home").json()
    assert not [k for k in home["kpis"] if k["module"] == "purchases"]
    assert not [s for s in home["shortcuts"] if s["module"] == "purchases"]
    # ses données restent, et protègent toujours les articles qu'elles désignent
    res = client.delete(f"/api/data/technical/articles/{article['id']}")
    assert res.status_code == 409 and "commandes fournisseurs" in res.json()["detail"]
    assert client.put("/api/settings/modules/purchases", json={"enabled": True}).status_code == 200
    assert client.get(f"{BASE}/orders/{order['id']}").json()["code"] == order["code"]


def test_meta_describes_the_module(client):
    meta = client.get("/api/meta").json()
    module = next(m for m in meta["modules"] if m["key"] == "purchases")
    assert module["slug"] == "achats" and module["label"] == ["Achats", "Purchasing"] and module["icon"] == "ShoppingCart"
    assert [(p["slug"], p["entity"]) for p in module["pages"]] == [("commandes", "purchases.orders"),
                                                                   ("fournisseurs", "purchases.suppliers")]
    orders = meta["entities"]["purchases.orders"]
    assert orders["label"] == ["Commande fournisseur", "Purchase order"] and orders["title"] == "code"
    assert [a["key"] for a in orders["actions"]] == ["send", "receive", "cancel"]
    assert [a["key"] for a in orders["actions"] if a["confirm"]] == ["receive", "cancel"]
    assert next(a for a in orders["actions"] if a["key"] == "cancel")["style"] == "danger"
    fields = {f["name"]: f for f in orders["fields"]}
    assert fields["status"]["readonly"] and fields["received_date"]["readonly"] and fields["code"]["prefix"] == "CF"
    assert [c["value"] for c in fields["status"]["choices"]] == ["draft", "sent", "received", "cancelled"]
    assert fields["late"]["computed"] and fields["total_ttc"]["computed"] and fields["warehouse_id"]["ref"] == "stock.warehouses"
    assert fields["supplier_id"]["required"] and fields["supplier_id"]["filter"] and fields["status"]["filter"]
    assert fields["expected_date"]["label"] == ["Livraison prévue", "Expected delivery"]
    assert fields["warehouse_id"]["label"][0] == "Entrepôt de réception" and not fields["warehouse_id"]["required"]
    assert [name for name, f in fields.items() if f["list"]] == ["code", "supplier_id", "order_date", "expected_date",
                                                                 "status", "total_ht", "late"]
    [lines] = orders["children"]
    line_fields = {f["name"]: f for f in lines["fields"]}
    assert list(line_fields) == ["article_id", "description", "quantity", "unit_price", "vat_rate", "amount"]
    assert line_fields["article_id"]["fill"] == ["description", "unit_price"] and line_fields["amount"]["computed"]
    assert [c["value"] for c in line_fields["vat_rate"]["choices"]] == [20, 10, 5.5, 2.1, 0]
    assert line_fields["vat_rate"]["default"] == 20 and line_fields["quantity"]["default"] == 1
    assert line_fields["unit_price"]["default"] == 0 and line_fields["description"]["required"]
    suppliers = meta["entities"]["purchases.suppliers"]
    assert suppliers["title"] == "name" and suppliers["can_delete"]
    assert suppliers["label"] == ["Fournisseur", "Supplier"] and suppliers["plural"] == ["Fournisseurs", "Suppliers"]
    supplier_fields = {f["name"]: f for f in suppliers["fields"]}
    assert supplier_fields["code"]["prefix"] == "FRN" and supplier_fields["code"]["readonly"]
    assert supplier_fields["country"]["default"] == "France" and supplier_fields["payment_terms_days"]["max"] == 120
    assert supplier_fields["payment_terms_days"]["default"] == 30 and supplier_fields["address"]["width"] == "full"
    assert supplier_fields["ordered_ytd"]["computed"] and supplier_fields["orders_count"]["computed"]
    assert supplier_fields["active"]["filter"] and supplier_fields["active"]["default"] is True
    assert supplier_fields["name"]["required"] and supplier_fields["name"]["search"] and supplier_fields["city"]["search"]


def test_home_kpis_follow_the_orders(client):
    def kpis():
        return {k["key"]: k for k in client.get("/api/home").json()["kpis"]}

    start = kpis()
    assert start["purchases.to_receive"]["path"] == "/achats/commandes?f_status=sent"
    assert start["purchases.late_deliveries"]["path"].startswith("/achats/commandes?f_status=sent")
    assert start["purchases.ordered_month"]["unit"] == "money"
    shortcut = next(s for s in client.get("/api/home").json()["shortcuts"] if s["key"] == "purchases.new_order")
    assert shortcut["path"] == "/achats/commandes?new=1" and shortcut["label"] == ["Commande fournisseur", "Purchase order"]
    supplier = _supplier(client)
    this_month = _order(client, supplier, [{"description": "Toile", "quantity": 2, "unit_price": 30.75, "vat_rate": 10}])
    overdue = _order(client, supplier, [{"description": "Encre", "quantity": 1, "unit_price": 80}],
                     order_date=f"{today().year - 1}-12-31", expected_date=_day(-1))
    _order(client, supplier, [{"description": "Brouillon", "quantity": 1, "unit_price": 500}])  # brouillon : ignoré
    for order in (this_month, overdue):
        _act(client, order, "send")
    now = kpis()
    assert now["purchases.to_receive"]["value"] == start["purchases.to_receive"]["value"] + 2
    assert now["purchases.late_deliveries"]["value"] == start["purchases.late_deliveries"]["value"] + 1
    assert now["purchases.late_deliveries"]["alert"] is True
    assert now["purchases.ordered_month"]["value"] == round(start["purchases.ordered_month"]["value"] + 61.5, 2)  # HT
    assert now["purchases.ordered_month"]["count"] == start["purchases.ordered_month"]["count"] + 1
    _act(client, this_month, "receive")   # reçue : plus à recevoir, toujours dans les achats du mois
    _act(client, overdue, "cancel")       # annulée : plus en retard
    end = kpis()
    assert end["purchases.to_receive"]["value"] == start["purchases.to_receive"]["value"]
    assert end["purchases.late_deliveries"]["value"] == start["purchases.late_deliveries"]["value"]
    assert end["purchases.ordered_month"]["value"] == now["purchases.ordered_month"]["value"]
    # chaque chiffre clé correspond à la liste qu'il ouvre
    sent = client.get(f"{BASE}/orders", params={"f_status": "sent", "size": 200}).json()
    assert end["purchases.to_receive"]["value"] == sent["total"]
    assert end["purchases.late_deliveries"]["value"] == len([r for r in sent["rows"] if r["late"]])


def test_kpis_are_offered_in_my_views(client):
    """« Mes vues » reconnaît un chiffre clé quand la demande cite son libellé : chaque libellé nomme ce qu'il compte,
    et les demandes sur d'autres sujets (factures en retard, encaissements) ne font pas apparaître les achats."""
    def metrics(text):
        widgets = dashboard.compose_offline(text, {})["spec"]["widgets"]
        return [w["params"]["metric"] for w in widgets if w["source"] == "kpi"]

    module = registry.get("purchases")
    assert [k.key for k in module.kpis] == ["to_receive", "late_deliveries", "ordered_month"]
    for kpi in module.kpis:
        for label in kpi.label:
            assert f"purchases.{kpi.key}" in metrics(f"Montre-moi : {label.lower()}"), label
    for text in ("mes factures en retard", "le total en retard", "combien j'ai encaissé ce mois-ci", "mes commandes à livrer"):
        assert not [m for m in metrics(text) if m.startswith("purchases.")], text
    # de bout en bout : la demande devient une carte, calculée par le module
    res = client.post("/api/dashboards/compose", json={"text": "Montre-moi les commandes fournisseurs à recevoir"})
    [card] = [w for w in res.json()["view"]["widgets"] if w["source"] == "kpi"]
    sent = client.get(f"{BASE}/orders", params={"f_status": "sent"}).json()["total"]
    assert card["params"]["metric"] == "purchases.to_receive" and card["data"]["value"] == sent
    assert card["data"]["path"] == "/achats/commandes?f_status=sent"
    month = client.post("/api/dashboards/render", json={"spec": {"widgets": [
        {"source": "kpi", "params": {"metric": "purchases.ordered_month"}}]}}).json()["widgets"][0]["data"]
    assert month["unit"] == "money" and month["label"] == ["Achats du mois", "Purchases this month"]
    # sans accès aux achats, ni la demande ni une vue enregistrée ne montrent ces chiffres
    make_member("commercial-vues@test.local", "sales")
    seller = login_as("commercial-vues@test.local")
    res = seller.post("/api/dashboards/compose", json={"text": "Montre-moi les commandes fournisseurs à recevoir"}).json()
    assert not [w for w in res["view"]["widgets"] if w["params"].get("metric", "").startswith("purchases.")]
    hidden = seller.post("/api/dashboards/render", json={"spec": {"widgets": [
        {"source": "kpi", "params": {"metric": "purchases.to_receive"}}]}}).json()
    assert hidden["widgets"] == [] and hidden["hidden"] == 1


def test_export_lists_computed_amounts(client):
    order = _order(client, _supplier(client), MIXED_LINES, supplier_ref="DEV-77", expected_date=_day(30))
    res = client.get(f"{BASE}/orders/export", params={"q": "DEV-77"})
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    header, *rows = list(csv.reader(io.StringIO(res.text.lstrip("﻿")), delimiter=";"))
    [row] = rows
    cells = dict(zip(header, row, strict=True))
    assert cells["Numéro"] == order["code"] and cells["Fournisseur"] == "Cartonnages Rhodaniens"
    assert (cells["Montant HT"], cells["TVA"], cells["Montant TTC"]) == ("238,84", "18,01", "256,85")
    assert cells["Statut"] == "Brouillon" and cells["En retard"] == "Non"
    english = client.get(f"{BASE}/orders/export", params={"q": "DEV-77", "lang": "en"}).text.lstrip("﻿")
    header, row = list(csv.reader(io.StringIO(english)))
    assert dict(zip(header, row, strict=True))["Amount incl. VAT"] == "256.85"


# ═════════════════════════════════════════════════════════════════════════
# Démonstration
# ═════════════════════════════════════════════════════════════════════════
def test_demo_data(client):
    # D'autres modules peuvent ajouter leurs propres données : on ne regarde que celles des Achats
    suppliers = {r["name"]: r for r in client.get(f"{BASE}/suppliers", params={"size": 200}).json()["rows"]}
    assert DEMO_SUPPLIERS <= set(suppliers)
    demo = [suppliers[name] for name in DEMO_SUPPLIERS]
    assert all(s["code"].startswith("FRN-") and s["email"].endswith(".example") and s["country"] == "France" for s in demo)
    assert {s["city"] for s in demo} <= {"Lyon", "Saint-Priest", "Villeurbanne", "Vénissieux"}
    assert suppliers["Imprimerie du Rhône"]["city"] == "Lyon" and suppliers["Emballages du Rhône"]["orders_count"] == 2
    orders = [r for r in client.get(f"{BASE}/orders", params={"size": 200}).json()["rows"]
              if r["supplier_id__label"] in DEMO_SUPPLIERS]
    assert sorted((r["supplier_id__label"], r["status"]) for r in orders) == [
        ("Emballages du Rhône", "draft"), ("Emballages du Rhône", "sent"), ("Imprimerie du Rhône", "sent"),
        ("Papeterie Lyonnaise", "received")]
    # reçue il y a 20 jours : 2000 feuilles à 0,40 et 1000 enveloppes à 0,17, entrées en stock au prix d'achat
    received = next(r for r in orders if r["status"] == "received")
    assert received["received_date"] == _day(-20)
    assert (received["total_ht"], received["total_vat"], received["total_ttc"]) == (970, 194, 1164)
    paper, envelope = article_id(PAPER), article_id("Enveloppe kraft C5")
    moves = _moves(received)
    assert {(m["article_id"], m["quantity"], m["unit_cost"]) for m in moves} == {(paper, 2000, 0.4), (envelope, 1000, 0.17)}
    assert {m["date"] for m in moves} == {_day(-20)} and {m["kind"] for m in moves} == {"receipt"}
    # envoyée il y a 15 jours, attendue il y a 5 jours : en retard
    late = [r for r in orders if r["late"]]
    assert [(r["supplier_id__label"], r["order_date"], r["expected_date"], r["total_ht"]) for r in late] == [
        ("Imprimerie du Rhône", _day(-15), _day(-5), 300)]
    # envoyée il y a 3 jours, attendue dans 2 jours
    coming = next(r for r in orders if r["status"] == "sent" and not r["late"])
    assert (coming["order_date"], coming["expected_date"], coming["total_ht"]) == (_day(-3), _day(2), 130)
    draft = next(r for r in orders if r["status"] == "draft")
    lines = client.get(f"{BASE}/orders/{draft['id']}").json()["lines"]
    assert [(line["article_id__label"], line["quantity"], line["unit_price"]) for line in lines] == [
        ("Papier de soie (feuille)", 500, 0.08)]
    assert not [m for r in orders if r["status"] != "received" for m in _moves(r)]  # seule la commande reçue a bougé le stock
    kpis = {k["key"]: k for k in client.get("/api/home").json()["kpis"]}
    all_sent = client.get(f"{BASE}/orders", params={"f_status": "sent", "size": 200}).json()
    assert kpis["purchases.to_receive"]["value"] == all_sent["total"] >= 2
    assert kpis["purchases.late_deliveries"]["value"] == len([r for r in all_sent["rows"] if r["late"]]) >= 1
    assert kpis["purchases.late_deliveries"]["alert"] is True
