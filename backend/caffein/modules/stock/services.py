# SPDX-License-Identifier: AGPL-3.0-or-later
"""Services de la Logistique : mouvements créés par les autres modules, stock disponible.

Les Ventes, les Achats et la Production ne connaissent pas la Logistique : ils annoncent un événement
(core/events.py) et ce module, s'il est actif, enregistre les mouvements correspondants.
"""

from __future__ import annotations

from datetime import date as date_cls

from ... import db
from ...core import entities
from ...core.modules import MANAGE
from ...utils import today


def default_warehouse_id() -> int:
    """Entrepôt par défaut (créé au besoin : « Entrepôt principal »)."""
    row = (db.fetch_one("SELECT id FROM stock_warehouses WHERE is_default = 1 AND active = 1 ORDER BY id LIMIT 1")
           or db.fetch_one("SELECT id FROM stock_warehouses WHERE active = 1 ORDER BY id LIMIT 1"))
    if row:
        return row["id"]
    return entities.save_row(entities.get("stock.warehouses"), {"name": "Entrepôt principal", "is_default": True}, MANAGE)


def on_hand(article_id: int, warehouse_id: int | None = None) -> float:
    """Stock actuel d'un article (tous entrepôts, ou un seul)."""
    sql, params = "SELECT COALESCE(SUM(quantity), 0) AS q FROM stock_movements WHERE article_id = ?", [article_id]
    if warehouse_id:
        sql += " AND warehouse_id = ?"
        params.append(warehouse_id)
    return round(db.fetch_one(sql, tuple(params))["q"], 6)


def _stocked(article_ids: set[int]) -> set[int]:
    """Articles qui se stockent (existants, et pas des services)."""
    if not article_ids:
        return set()
    marks = ", ".join("?" for _ in article_ids)
    return {r["id"] for r in db.fetch_all(f"SELECT id FROM technical_articles WHERE id IN ({marks}) AND kind != 'service'",
                                          tuple(article_ids))}


def post(kind: str, lines: list[dict], *, sign: int, reference: str = "", date: str | None = None, source: str = "",
         warehouse_id: int | None = None) -> int:
    """Enregistre les mouvements d'un document (une ligne par article stocké) et renvoie leur nombre.
    Un même document (`source`) n'est compté qu'une fois par type de mouvement, même si deux demandes
    arrivent en même temps (contrôle et écriture sous le même verrou)."""
    stocked = _stocked({line["article_id"] for line in lines if line.get("article_id")})
    rows = [line for line in lines if line.get("article_id") in stocked and line.get("quantity")]
    if not rows:
        return 0
    warehouse = warehouse_id or default_warehouse_id()
    day = date or today().isoformat()
    now = db.now_iso()
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")  # contrôle du document, numérotation et insertion ensemble
        if source and conn.execute("SELECT 1 FROM stock_movements WHERE source = ? AND kind = ? LIMIT 1",
                                   (source, kind)).fetchone():
            return 0
        stem = f"MVT-{day[:4]}-"
        first = entities.next_code("stock_movements", "code", "MVT", ref=date_cls.fromisoformat(day), conn=conn)
        seq = int(first[len(stem):]) - 1
        for line in rows:
            seq += 1
            conn.execute(
                "INSERT INTO stock_movements (code, date, kind, article_id, warehouse_id, quantity, unit_cost, reference, source,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"{stem}{seq:04d}", day, kind, line["article_id"], warehouse, sign * abs(line["quantity"]),
                 line.get("unit_cost"), reference[:80], source, now, now))
    return len(rows)


def _message(count: int) -> str | None:
    return f"Stock : {count} mouvement(s) enregistré(s)." if count else None


# ── Abonnements aux événements des autres modules ──────────────────────
def on_sales_delivered(payload: dict) -> str | None:
    count = post("delivery", payload.get("lines", []), sign=-1, reference=payload.get("code", ""), date=payload.get("date"),
                 source=f"sales.orders:{payload.get('order_id')}")
    return _message(count)


def on_purchase_received(payload: dict) -> str | None:
    lines = [{**line, "unit_cost": line.get("unit_price")} for line in payload.get("lines", [])]
    count = post("receipt", lines, sign=1, reference=payload.get("code", ""), date=payload.get("date"),
                 source=f"purchases.orders:{payload.get('order_id')}", warehouse_id=payload.get("warehouse_id"))
    return _message(count)


def on_production_completed(payload: dict) -> str | None:
    source = f"production.orders:{payload.get('order_id')}"
    reference, date = payload.get("code", ""), payload.get("date")
    produced = post("production", [{"article_id": payload.get("article_id"), "quantity": payload.get("quantity")}], sign=1,
                    reference=reference, date=date, source=source, warehouse_id=payload.get("warehouse_id"))
    consumed = post("consumption", payload.get("components", []), sign=-1, reference=reference, date=date, source=source,
                    warehouse_id=payload.get("warehouse_id"))
    return _message(produced + consumed)


EVENTS = {
    "sales.order_delivered": on_sales_delivered,
    "purchases.order_received": on_purchase_received,
    "production.order_completed": on_production_completed,
}
