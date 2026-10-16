# SPDX-License-Identifier: AGPL-3.0-or-later
"""Logistique : entrepôts, mouvements de stock, niveaux et réapprovisionnement.

Le stock n'est jamais saisi : c'est la somme des mouvements (registre définitif, corrigé par des ajustements).
Les niveaux sont des vues SQL ; la valeur du stock et les quantités à commander sont calculées en Python.
"""

from __future__ import annotations

from ... import db
from ...core.entities import Entity, Field
from ...utils import cents, today

MIGRATIONS = [
    (1, """
CREATE TABLE IF NOT EXISTS stock_warehouses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    is_default INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_warehouses_code ON stock_warehouses(code) WHERE code != '';

-- Registre des mouvements. article_id : article des Données techniques (pas de clé étrangère entre modules).
-- quantity est signée (+ entrée, − sortie). source : document d'origine (« sales.orders:12 »), pour ne rien compter deux fois.
CREATE TABLE IF NOT EXISTS stock_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL DEFAULT '',
    date TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('receipt', 'delivery', 'production', 'consumption', 'adjustment')),
    article_id INTEGER NOT NULL,
    warehouse_id INTEGER NOT NULL REFERENCES stock_warehouses(id) ON DELETE RESTRICT,
    quantity REAL NOT NULL,
    unit_cost REAL,
    reference TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_movements_code ON stock_movements(code) WHERE code != '';
CREATE INDEX IF NOT EXISTS idx_stock_movements_article ON stock_movements(article_id, warehouse_id);
CREATE INDEX IF NOT EXISTS idx_stock_movements_source ON stock_movements(source, kind);

-- Niveau par article et par entrepôt
CREATE VIEW IF NOT EXISTS stock_levels AS
    SELECT m.article_id * 100000 + m.warehouse_id AS id, m.article_id, m.warehouse_id,
           COALESCE(a.name, '#' || m.article_id) AS article_name,
           ROUND(SUM(m.quantity), 6) AS quantity, MAX(m.date) AS last_movement
    FROM stock_movements m LEFT JOIN technical_articles a ON a.id = m.article_id
    GROUP BY m.article_id, m.warehouse_id;

-- État par article (tous entrepôts) : à réapprovisionner sous le stock minimum, en rupture à zéro
CREATE VIEW IF NOT EXISTS stock_status AS
    SELECT a.id AS id, a.id AS article_id, a.name AS article_name, a.unit AS unit,
           ROUND(COALESCE(SUM(m.quantity), 0), 6) AS quantity, a.min_stock AS min_stock, a.reorder_qty AS reorder_qty,
           CASE WHEN a.min_stock IS NOT NULL AND COALESCE(SUM(m.quantity), 0) < a.min_stock THEN 'reorder'
                WHEN COALESCE(SUM(m.quantity), 0) <= 0 THEN 'out'
                ELSE 'ok' END AS status
    FROM technical_articles a LEFT JOIN stock_movements m ON m.article_id = a.id
    WHERE a.kind != 'service' AND a.active = 1
    GROUP BY a.id;
"""),
]

KINDS = (
    ("receipt", ("Entrée", "Receipt"), "good"), ("delivery", ("Sortie", "Issue"), "info"),
    ("production", ("Production", "Production"), "accent"), ("consumption", ("Consommation", "Consumption"), "outline"),
    ("adjustment", ("Ajustement", "Adjustment"), "warn"),
)
MANUAL_KINDS = ("receipt", "delivery", "adjustment")  # les autres viennent des Achats, des Ventes et de la Production
STATUSES = (("reorder", ("À réapprovisionner", "To reorder"), "bad"), ("out", ("Rupture", "Out of stock"), "warn"),
            ("ok", ("Disponible", "In stock"), "good"))


def _today() -> str:
    return today().isoformat()


# ═════════════════════════════════════════════════════════════════════════
# Entrepôts
# ═════════════════════════════════════════════════════════════════════════
def _warehouse_after_save(row_id: int, created: bool) -> None:
    row = db.fetch_one("SELECT is_default FROM stock_warehouses WHERE id = ?", (row_id,))
    if row and row["is_default"]:  # un seul entrepôt par défaut
        db.execute("UPDATE stock_warehouses SET is_default = 0 WHERE id != ?", (row_id,))


WAREHOUSES = Entity(
    module="stock", name="warehouses", table="stock_warehouses", label=("Entrepôt", "Warehouse"),
    plural=("Entrepôts", "Warehouses"), title="name", subtitle="code", order_by="name COLLATE NOCASE", icon="Warehouse",
    active="active",
    description=("Vos lieux de stockage. Les livraisons, réceptions et fabrications utilisent l'entrepôt par défaut.",
                 "Your storage locations. Deliveries, receipts and production use the default warehouse."),
    fields=[
        Field("code", ("Code", "Code"), type="code", prefix="ENT", yearly=False, readonly=True, list=True),
        Field("name", ("Nom", "Name"), required=True, unique=True, list=True, search=True, maxlength=120),
        Field("address", ("Adresse", "Address"), width="full", maxlength=240, list=True),
        Field("is_default", ("Entrepôt par défaut", "Default warehouse"), type="bool", default=False, list=True),
        Field("active", ("Actif", "Active"), type="bool", default=True, filter=True),
        Field("notes", ("Notes", "Notes"), type="longtext", width="full"),
    ],
    after_save=_warehouse_after_save,
)


# ═════════════════════════════════════════════════════════════════════════
# Mouvements
# ═════════════════════════════════════════════════════════════════════════
def _movement_prepare(values: dict, existing: dict | None) -> None:
    """Saisie manuelle : quantité positive pour une entrée ou une sortie (le signe suit le type),
    signée pour un ajustement ; l'entrepôt par défaut si aucun n'est choisi."""
    if existing is not None:
        return
    from .services import default_warehouse_id

    if values.get("warehouse_id") is None:
        values["warehouse_id"] = default_warehouse_id()
    quantity = values.get("quantity")
    if quantity is not None and values.get("kind") in ("receipt", "delivery"):
        values["quantity"] = abs(quantity) if values["kind"] == "receipt" else -abs(quantity)


def _movement_validate(values: dict, existing: dict | None) -> None:
    if existing is None and values.get("kind") not in MANUAL_KINDS:
        raise ValueError("Type : les mouvements de production viennent des ordres de fabrication.")
    if not values.get("quantity"):
        raise ValueError("Quantité : elle ne peut pas être nulle.")
    article = db.fetch_one("SELECT kind FROM technical_articles WHERE id = ?", (values.get("article_id"),))
    if article and article["kind"] == "service":
        raise ValueError("Article : un service ne se stocke pas.")


MOVEMENTS = Entity(
    module="stock", name="movements", table="stock_movements", label=("Mouvement de stock", "Stock movement"),
    plural=("Mouvements de stock", "Stock movements"), title="code", order_by="date DESC, id DESC", icon="ArrowLeftRight",
    description=("Chaque entrée et chaque sortie, avec son origine. Un mouvement est définitif : on corrige par un ajustement.",
                 "Every receipt and issue, with its origin. A movement is final: corrections are adjustments."),
    fields=[
        Field("code", ("Numéro", "Number"), type="code", prefix="MVT", readonly=True, list=True, search=True),
        Field("date", ("Date", "Date"), type="date", default=_today, required=True, list=True),
        Field("kind", ("Type", "Type"), type="enum", choices=KINDS, default="adjustment", required=True, list=True, filter=True,
              help=("Entrée et sortie : quantité positive. Ajustement : + pour ajouter, − pour retirer.",
                    "Receipt and issue: positive quantity. Adjustment: + to add, − to remove.")),
        Field("article_id", ("Article", "Item"), type="ref", ref="technical.articles", required=True, list=True, filter=True),
        Field("warehouse_id", ("Entrepôt", "Warehouse"), type="ref", ref="stock.warehouses", list=True, filter=True),
        Field("quantity", ("Quantité", "Quantity"), type="decimal", required=True, min=-1_000_000_000, max=1_000_000_000, list=True),
        Field("unit_cost", ("Coût unitaire", "Unit cost"), type="money", min=0, max=1_000_000_000),
        Field("reference", ("Référence", "Reference"), list=True, search=True, maxlength=80,
              help=("Bon de livraison, commande, inventaire…", "Delivery note, order, stock count…")),
        Field("notes", ("Notes", "Notes"), type="longtext", width="full"),
        Field("source", ("Origine", "Origin"), readonly=True, hidden=True),
    ],
    prepare=_movement_prepare, validate=_movement_validate,
    locked=lambda row: "Un mouvement de stock est définitif : pour corriger, saisissez un ajustement.",
)


# ═════════════════════════════════════════════════════════════════════════
# Niveaux (vues SQL, consultation)
# ═════════════════════════════════════════════════════════════════════════
def _status_values(rows: list[dict]) -> None:
    """Valeur du stock (quantité × coût de revient) et quantité conseillée à commander."""
    from ..technical.costing import cost_price

    memo: dict = {}
    for row in rows:
        quantity = row.get("quantity") or 0
        cost = cost_price(row.get("article_id"), memo)
        row["value"] = cents(max(quantity, 0) * cost) if cost is not None else None
        minimum = row.get("min_stock")
        if minimum is not None and quantity < minimum:
            row["to_order"] = round(max(row.get("reorder_qty") or 0, minimum - quantity), 3)
        else:
            row["to_order"] = None


STOCK = Entity(
    module="stock", name="stock", table="stock_status", label=("Stock d'un article", "Item stock"),
    plural=("Stock par article", "Stock by item"), title="article_name", order_by="article_name COLLATE NOCASE",
    icon="Boxes", readonly=True,
    description=("Le stock de chaque article, tous entrepôts confondus, et ce qu'il faut recommander.",
                 "Each item's stock across warehouses, and what to reorder."),
    fields=[
        Field("article_name", ("Article", "Item"), list=True, search=True),
        Field("article_id", ("Fiche article", "Item record"), type="ref", ref="technical.articles"),
        Field("quantity", ("En stock", "On hand"), type="decimal", list=True),
        Field("unit", ("Unité", "Unit"), list=True),
        Field("min_stock", ("Stock minimum", "Minimum stock"), type="decimal", list=True),
        Field("to_order", ("À commander", "To order"), type="decimal", computed=True, list=True),
        Field("value", ("Valeur", "Value"), type="money", computed=True, list=True),
        Field("status", ("État", "Status"), type="enum", choices=STATUSES, list=True, filter=True),
        Field("reorder_qty", ("Quantité de réapprovisionnement", "Reorder quantity"), type="decimal"),
    ],
    compute=_status_values,
)

LEVELS = Entity(
    module="stock", name="levels", table="stock_levels", label=("Stock par entrepôt", "Stock by warehouse"),
    plural=("Stock par entrepôt", "Stock by warehouse"), title="article_name", order_by="article_name COLLATE NOCASE",
    icon="Warehouse", readonly=True,
    description=("Le stock de chaque article dans chaque entrepôt.", "Each item's stock in each warehouse."),
    fields=[
        Field("article_name", ("Article", "Item"), list=True, search=True),
        Field("article_id", ("Fiche article", "Item record"), type="ref", ref="technical.articles"),
        Field("warehouse_id", ("Entrepôt", "Warehouse"), type="ref", ref="stock.warehouses", list=True, filter=True),
        Field("quantity", ("En stock", "On hand"), type="decimal", list=True),
        Field("last_movement", ("Dernier mouvement", "Last movement"), type="date", list=True),
    ],
)

ENTITIES = [STOCK, MOVEMENTS, WAREHOUSES, LEVELS]
