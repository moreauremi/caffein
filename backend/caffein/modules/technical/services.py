# SPDX-License-Identifier: AGPL-3.0-or-later
"""Services des Données techniques pour les autres modules (Production, Logistique…).

Les autres modules n'accèdent aux articles et aux nomenclatures que par ces fonctions : le jour où le schéma
évolue, seules elles changent.
"""

from __future__ import annotations

from ... import db
from .costing import bom_line_need, cost_price  # noqa: F401 (cost_price : pour les autres modules)


def article(article_id: int | None) -> dict | None:
    if not article_id:
        return None
    return db.fetch_one("SELECT id, code, name, kind, unit, sale_price, purchase_price, min_stock, reorder_qty, active "
                        "FROM technical_articles WHERE id = ?", (article_id,))


def is_stocked(article_id: int | None) -> bool:
    """Un service ne se stocke pas ; un article inconnu non plus."""
    row = article(article_id)
    return bool(row and row["kind"] != "service")


def active_bom(article_id: int) -> dict | None:
    """Nomenclature active la plus récente de l'article, avec ses lignes."""
    bom = db.fetch_one("SELECT id, code, name, quantity FROM technical_boms WHERE article_id = ? AND active = 1 "
                       "ORDER BY id DESC LIMIT 1", (article_id,))
    if bom:
        bom["lines"] = db.fetch_all("SELECT article_id, quantity, scrap_rate FROM technical_bom_lines WHERE bom_id = ? "
                                    "AND article_id IS NOT NULL ORDER BY position, id", (bom["id"],))
    return bom


def components_for(article_id: int, quantity: float) -> list[dict]:
    """Besoins en composants pour fabriquer `quantity` unités : [{article_id, quantity}], pertes comprises.
    Liste vide si l'article n'a pas de nomenclature active."""
    bom = active_bom(article_id)
    if not bom or not bom["quantity"]:
        return []
    factor = quantity / bom["quantity"]
    needs: dict[int, float] = {}
    for line in bom["lines"]:
        needs[line["article_id"]] = round(needs.get(line["article_id"], 0) + bom_line_need(line, factor), 6)
    return [{"article_id": a, "quantity": q} for a, q in needs.items()]


def active_routing(article_id: int) -> dict | None:
    routing = db.fetch_one("SELECT id, code, name FROM technical_routings WHERE article_id = ? AND active = 1 "
                           "ORDER BY id DESC LIMIT 1", (article_id,))
    if routing:
        routing["steps"] = db.fetch_all(
            "SELECT s.workcenter_id, w.name AS workcenter, s.description, s.setup_minutes, s.run_minutes, w.hourly_cost "
            "FROM technical_routing_steps s LEFT JOIN technical_workcenters w ON w.id = s.workcenter_id "
            "WHERE s.routing_id = ? ORDER BY s.position, s.id", (routing["id"],))
    return routing
