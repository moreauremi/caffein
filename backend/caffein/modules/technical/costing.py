# SPDX-License-Identifier: AGPL-3.0-or-later
"""Coûts de revient, calculés en Python à partir des tables (jamais stockés : ils suivent les prix).

- coût d'achat : celui de l'article, s'il est acheté ;
- sinon coût de fabrication : matière (nomenclature active, composants valorisés de proche en proche)
  + main-d'œuvre et machines (gamme active : temps unitaire × coût horaire du poste).
"""

from __future__ import annotations

from ... import db

MAX_DEPTH = 20


def bom_line_need(line: dict, factor: float = 1.0) -> float:
    """Quantité de composant pour `factor` lots de la nomenclature, pertes comprises."""
    return round((line.get("quantity") or 0) * factor * (1 + (line.get("scrap_rate") or 0) / 100), 6)


def routing_unit_cost(article_id: int) -> float | None:
    rows = db.fetch_all(
        "SELECT s.run_minutes, w.hourly_cost FROM technical_routings r JOIN technical_routing_steps s ON s.routing_id = r.id "
        "LEFT JOIN technical_workcenters w ON w.id = s.workcenter_id WHERE r.id = (SELECT id FROM technical_routings "
        "WHERE article_id = ? AND active = 1 ORDER BY id DESC LIMIT 1)", (article_id,))
    if not rows:
        return None
    return round(sum((r["run_minutes"] or 0) / 60 * (r["hourly_cost"] or 0) for r in rows), 4)


def material_cost(article_id: int, memo: dict | None = None, _stack: tuple = ()) -> float | None:
    """Coût matière d'une unité fabriquée (nomenclature active), ou None sans nomenclature."""
    bom = db.fetch_one("SELECT id, quantity FROM technical_boms WHERE article_id = ? AND active = 1 ORDER BY id DESC LIMIT 1",
                       (article_id,))
    if not bom or not bom["quantity"]:
        return None
    total = 0.0
    for line in db.fetch_all("SELECT article_id, quantity, scrap_rate FROM technical_bom_lines WHERE bom_id = ? "
                             "AND article_id IS NOT NULL", (bom["id"],)):
        cost = cost_price(line["article_id"], memo, (*_stack, article_id))
        total += bom_line_need(line) * (cost or 0)
    return round(total / bom["quantity"], 4)


def cost_price(article_id: int | None, memo: dict | None = None, _stack: tuple = ()) -> float | None:
    """Coût de revient unitaire d'un article : coût d'achat, sinon matière + fabrication. None si inconnu."""
    if not article_id:
        return None
    memo = memo if memo is not None else {}
    if article_id in memo:
        return memo[article_id]
    if article_id in _stack or len(_stack) > MAX_DEPTH:  # nomenclature circulaire : on s'arrête
        return None
    row = db.fetch_one("SELECT purchase_price FROM technical_articles WHERE id = ?", (article_id,))
    if row is None:
        cost = None
    elif row["purchase_price"] is not None:
        cost = row["purchase_price"]
    else:
        material = material_cost(article_id, memo, _stack)
        labour = routing_unit_cost(article_id)
        cost = None if material is None and labour is None else round((material or 0) + (labour or 0), 4)
    memo[article_id] = cost
    return cost
