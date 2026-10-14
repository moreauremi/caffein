# SPDX-License-Identifier: AGPL-3.0-or-later
"""Données de démonstration des commandes clients (les factures et devis viennent de seed.py)."""

from __future__ import annotations

from datetime import timedelta

from ... import db
from ...core import entities
from ...core import modules as registry
from ...core.modules import MANAGE
from ...utils import today

# (client, jours avant aujourd'hui, statut visé, référence client, lignes [(article ou désignation, quantité, prix)])
ORDERS = [
    ("Kairos Conseil", 9, "delivered", "BC-4471", [("Kakémono 85×200 cm", 2, None)]),
    ("Atelier Nova", 4, "confirmed", "", [("Kit papeterie de marque", 3, None), ("Heure de conception graphique", 4, None)]),
    ("Maison Verde", 1, "draft", "", [("Flyers A5, lot de 500", 2, None), ("Livraison express", 1, 25)]),
]


def seed_demo() -> None:
    orders = entities.get("sales.orders")
    clients = {r["name"]: r["id"] for r in db.fetch_all("SELECT id, name FROM clients")}
    articles = {}
    if registry.is_enabled("technical"):
        articles = {r["name"]: r for r in db.fetch_all("SELECT id, name, sale_price FROM technical_articles")}
    for client, days_ago, status, ref, lines in ORDERS:
        if client not in clients:
            continue
        day = (today() - timedelta(days=days_ago)).isoformat()
        rows = []
        for label, quantity, price in lines:
            article = articles.get(label)
            rows.append({"article_id": article["id"] if article else None, "description": label, "quantity": quantity,
                         "unit_price": price if price is not None else (article or {}).get("sale_price") or 0})
        order_id = entities.save_row(orders, {"client_id": clients[client], "order_date": day, "customer_ref": ref,
                                              "lines": rows}, MANAGE)
        if status in ("confirmed", "delivered"):
            entities.run_action(orders, order_id, "confirm", {}, {}, MANAGE)
        if status == "delivered":
            db.execute("UPDATE sales_orders SET delivery_date = ? WHERE id = ?", ((today() - timedelta(days=days_ago - 2)).isoformat(),
                                                                                 order_id))
            entities.run_action(orders, order_id, "deliver", {}, {}, MANAGE)
