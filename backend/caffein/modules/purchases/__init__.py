# SPDX-License-Identifier: AGPL-3.0-or-later
"""Achats : fournisseurs, commandes fournisseurs et réceptions (entrée en stock si la Logistique est active)."""

from __future__ import annotations

from ... import db
from ...core.modules import Kpi, Module, Page, Shortcut
from ...utils import add_months, cents, today
from .demo import seed_demo
from .entities import ENTITIES, MIGRATIONS
from .figures import is_late, placed_between


def _to_receive() -> dict:
    """Commandes envoyées au fournisseur, pas encore reçues."""
    n = db.fetch_one("SELECT COUNT(*) AS n FROM purchases_orders WHERE status = 'sent'")["n"]
    return {"value": n, "count": n}


def _late_deliveries() -> dict:
    """Commandes envoyées dont la date de livraison prévue est passée (même règle que la colonne « En retard »)."""
    n = sum(1 for row in db.fetch_all("SELECT status, expected_date FROM purchases_orders "
                                      "WHERE status = 'sent' AND expected_date IS NOT NULL") if is_late(row))
    return {"value": n, "count": n}


def _ordered_month() -> dict:
    """Montant HT des commandes envoyées ou reçues datées de ce mois-ci, et leur nombre."""
    start = today().replace(day=1)
    figures = placed_between(start, add_months(start, 1)).values()
    return {"value": cents(sum(f["total_ht"] for f in figures)), "count": sum(f["count"] for f in figures)}


MODULE = Module(
    key="purchases", slug="achats", label=("Achats", "Purchasing"),
    description=("Fournisseurs, commandes fournisseurs et réceptions.", "Suppliers, purchase orders and receipts."),
    icon="ShoppingCart", order=30,
    migrations=MIGRATIONS, entities=ENTITIES,
    pages=[
        Page("commandes", ("Commandes fournisseurs", "Purchase orders"), entity="purchases.orders", icon="ShoppingCart"),
        Page("fournisseurs", ("Fournisseurs", "Suppliers"), entity="purchases.suppliers", icon="Truck"),
    ],
    # Libellés complets (l'objet est nommé) : « Mes vues » reconnaît un chiffre clé quand la demande cite son libellé
    kpis=[
        Kpi("to_receive", ("Commandes fournisseurs à recevoir", "Purchase orders to receive"), _to_receive,
            icon="PackageOpen", foot=("envoyées, livraison attendue", "sent, awaiting delivery"),
            path="/achats/commandes?f_status=sent"),
        Kpi("late_deliveries", ("Livraisons fournisseurs en retard", "Late supplier deliveries"), _late_deliveries,
            icon="Hourglass", foot=("date de livraison prévue dépassée", "expected delivery date passed"),
            path="/achats/commandes?f_status=sent&sort=expected_date", alert=lambda d: (d.get("value") or 0) > 0),
        Kpi("ordered_month", ("Achats du mois", "Purchases this month"), _ordered_month, unit="money", icon="ShoppingCart",
            foot=("{n} commande(s) passée(s), HT", "{n} order(s) placed, excl. VAT"), path="/achats/commandes"),
    ],
    shortcuts=[Shortcut("new_order", ("Commande fournisseur", "Purchase order"), "/achats/commandes?new=1", icon="ShoppingCart")],
    seed_demo=seed_demo,
    reset_tables=("purchases_order_lines", "purchases_orders", "purchases_suppliers"),
)
