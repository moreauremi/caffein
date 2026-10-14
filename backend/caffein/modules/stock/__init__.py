# SPDX-License-Identifier: AGPL-3.0-or-later
"""Logistique : entrepôts, mouvements et niveaux de stock, réapprovisionnement."""

from __future__ import annotations

from ... import db
from ...core.modules import Kpi, Module, Page, Shortcut
from ...utils import today
from .demo import seed_demo
from .entities import ENTITIES, MIGRATIONS
from .services import EVENTS


def _to_reorder() -> dict:
    n = db.fetch_one("SELECT COUNT(*) AS n FROM stock_status WHERE status = 'reorder'")["n"]
    return {"value": n, "count": n}


def _stock_value() -> dict:
    from ..technical.costing import cost_price

    memo: dict = {}
    total = sum(max(r["quantity"], 0) * (cost_price(r["article_id"], memo) or 0)
                for r in db.fetch_all("SELECT article_id, quantity FROM stock_status WHERE quantity > 0"))
    return {"value": round(total, 2)}


def _movements_month() -> dict:
    n = db.fetch_one("SELECT COUNT(*) AS n FROM stock_movements WHERE date >= ?", (today().replace(day=1).isoformat(),))["n"]
    return {"value": n, "count": n}


MODULE = Module(
    key="stock", slug="logistique", label=("Logistique", "Logistics"),
    description=("Entrepôts, mouvements et niveaux de stock, articles à réapprovisionner. Les livraisons, réceptions et "
                 "fabrications mettent le stock à jour toutes seules.",
                 "Warehouses, stock movements and levels, items to reorder. Deliveries, receipts and production "
                 "update the stock by themselves."),
    icon="Warehouse", order=60, depends=("technical",),
    migrations=MIGRATIONS, entities=ENTITIES,
    pages=[
        Page("stock", ("Stock", "Stock"), entity="stock.stock", icon="Boxes"),
        Page("mouvements", ("Mouvements", "Movements"), entity="stock.movements", icon="ArrowLeftRight"),
        Page("par-entrepot", ("Par entrepôt", "By warehouse"), entity="stock.levels", icon="Warehouse"),
        Page("entrepots", ("Entrepôts", "Warehouses"), entity="stock.warehouses", icon="Store"),
    ],
    events=EVENTS,
    kpis=[
        Kpi("to_reorder", ("À réapprovisionner", "To reorder"), _to_reorder, icon="PackageMinus",
            foot=("article(s) sous le stock minimum", "item(s) below minimum stock"), path="/logistique/stock?f_status=reorder",
            alert=lambda d: (d.get("value") or 0) > 0),
        Kpi("stock_value", ("Valeur du stock", "Stock value"), _stock_value, unit="money", icon="Warehouse",
            foot=("au coût de revient", "at cost price"), path="/logistique/stock"),
        Kpi("movements_month", ("Mouvements ce mois", "Movements this month"), _movements_month, icon="ArrowLeftRight",
            path="/logistique/mouvements"),
    ],
    shortcuts=[Shortcut("new_movement", ("Mouvement de stock", "Stock movement"), "/logistique/mouvements?new=1",
                        icon="ArrowLeftRight")],
    seed_demo=seed_demo,
    reset_tables=("stock_movements", "stock_warehouses"),
)
