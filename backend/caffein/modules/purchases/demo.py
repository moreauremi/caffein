# SPDX-License-Identifier: AGPL-3.0-or-later
"""Données de démonstration : les fournisseurs du studio et ses commandes (une reçue, deux attendues dont une
en retard, une en préparation), sur les articles des Données techniques."""

from __future__ import annotations

from datetime import timedelta

from ... import db
from ...core import entities
from ...core import modules as registry
from ...core.modules import MANAGE
from ...utils import today

# Numéros de téléphone de la plage réservée à la fiction (04 65 71 xx xx)
SUPPLIERS = [
    {"name": "Papeterie Lyonnaise", "contact_name": "Martine Girard", "email": "commandes@papeterie-lyonnaise.example",
     "phone": "04 65 71 20 14", "address": "8 rue Mercière", "zip_code": "69002", "city": "Lyon", "payment_terms_days": 30,
     "notes": "Papiers d'impression et enveloppes. Franco de port à partir de 300 € HT."},
    {"name": "Emballages du Rhône", "contact_name": "Karim Benali", "email": "ventes@emballages-du-rhone.example",
     "phone": "04 65 71 38 52", "address": "112 route de Lyon", "zip_code": "69800", "city": "Saint-Priest",
     "payment_terms_days": 45, "notes": "Boîtes cadeaux et papier de soie pour les kits."},
    {"name": "Imprimerie du Rhône", "contact_name": "Thomas Roux", "email": "devis@imprimerie-du-rhone.example",
     "phone": "04 65 71 47 09", "address": "55 avenue Jean Jaurès", "zip_code": "69007", "city": "Lyon",
     "payment_terms_days": 30, "notes": "Impression grand format (kakémonos) et flyers."},
]

# (fournisseur, commandée il y a … jours, livraison prévue dans … jours (négatif : date passée), statut visé,
#  référence fournisseur, lignes [(article, quantité, prix unitaire HT)])
ORDERS = [
    ("Papeterie Lyonnaise", 27, -20, "received", "ARC-24118",
     [("Papier couché 350 g, feuille SRA3", 2000, 0.40), ("Enveloppe kraft C5", 1000, 0.17)]),
    ("Imprimerie du Rhône", 15, -5, "sent", "DEV-0912", [("Kakémono 85×200 cm", 5, 60)]),
    ("Emballages du Rhône", 3, 2, "sent", "", [("Boîte cadeau kraft 22×16 cm", 100, 1.30)]),
    ("Emballages du Rhône", 1, None, "draft", "", [("Papier de soie (feuille)", 500, 0.08)]),
]
RECEIVED_DAYS_AGO = 20


def _day(offset: int) -> str:
    return (today() + timedelta(days=offset)).isoformat()


def seed_demo() -> None:
    suppliers, orders = entities.get("purchases.suppliers"), entities.get("purchases.orders")
    ids = {data["name"]: entities.save_row(suppliers, data, MANAGE) for data in SUPPLIERS}
    articles = {}
    if registry.is_enabled("technical"):
        articles = {r["name"]: r["id"] for r in db.fetch_all("SELECT id, name FROM technical_articles")}
    for supplier, days_ago, expected_in, status, ref, lines in ORDERS:
        rows = [{"article_id": articles.get(label), "description": label, "quantity": quantity, "unit_price": price}
                for label, quantity, price in lines]
        order_id = entities.save_row(orders, {
            "supplier_id": ids[supplier], "order_date": _day(-days_ago), "supplier_ref": ref, "lines": rows,
            "expected_date": _day(expected_in) if expected_in is not None else None,
        }, MANAGE)
        if status in ("sent", "received"):
            entities.run_action(orders, order_id, "send", {}, {}, MANAGE)
        if status == "received":  # la Logistique, active en démonstration, fait entrer les articles en stock
            entities.run_action(orders, order_id, "receive", {"date": _day(-RECEIVED_DAYS_AGO)}, {}, MANAGE)
