# SPDX-License-Identifier: AGPL-3.0-or-later
"""Données techniques : familles, articles, nomenclatures, postes de charge, gammes.

Les articles sont le référentiel commun : les Ventes, les Achats, la Logistique et la Production les désignent
par `technical.articles` (champs `name`, `sale_price`, `purchase_price`, `unit`, `kind`, `min_stock`…).
Les coûts (matière d'une nomenclature, temps et coût d'une gamme, marge d'un article) sont calculés ici, en Python.
"""

from __future__ import annotations

from ... import db
from ...core.entities import Child, Entity, Field
from .costing import bom_line_need, cost_price

MIGRATIONS = [
    (1, """
CREATE TABLE IF NOT EXISTS technical_families (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_technical_families_name ON technical_families(name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS technical_articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'goods' CHECK (kind IN ('goods', 'raw', 'semi', 'finished', 'service')),
    family_id INTEGER REFERENCES technical_families(id) ON DELETE SET NULL,
    unit TEXT NOT NULL DEFAULT 'u',
    sale_price REAL,
    purchase_price REAL,
    vat_rate REAL,
    min_stock REAL,
    reorder_qty REAL,
    lead_time_days INTEGER,
    barcode TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_technical_articles_code ON technical_articles(code) WHERE code != '';
CREATE INDEX IF NOT EXISTS idx_technical_articles_family ON technical_articles(family_id);

-- Nomenclature : ce qu'il faut pour fabriquer `quantity` unités de l'article
CREATE TABLE IF NOT EXISTS technical_boms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL DEFAULT '',
    article_id INTEGER REFERENCES technical_articles(id) ON DELETE RESTRICT,
    name TEXT NOT NULL DEFAULT '',
    quantity REAL NOT NULL DEFAULT 1 CHECK (quantity > 0),
    active INTEGER NOT NULL DEFAULT 1,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_technical_boms_code ON technical_boms(code) WHERE code != '';
CREATE TABLE IF NOT EXISTS technical_bom_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bom_id INTEGER NOT NULL REFERENCES technical_boms(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    article_id INTEGER REFERENCES technical_articles(id) ON DELETE RESTRICT,
    quantity REAL NOT NULL DEFAULT 1,
    scrap_rate REAL NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_technical_bom_lines_bom ON technical_bom_lines(bom_id, position);

CREATE TABLE IF NOT EXISTS technical_workcenters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'machine' CHECK (kind IN ('machine', 'manual', 'subcontracting')),
    hourly_cost REAL,
    capacity_hours REAL,
    active INTEGER NOT NULL DEFAULT 1,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_technical_workcenters_code ON technical_workcenters(code) WHERE code != '';

-- Gamme : les opérations pour fabriquer l'article, poste par poste
CREATE TABLE IF NOT EXISTS technical_routings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL DEFAULT '',
    article_id INTEGER REFERENCES technical_articles(id) ON DELETE RESTRICT,
    name TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_technical_routings_code ON technical_routings(code) WHERE code != '';
CREATE TABLE IF NOT EXISTS technical_routing_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    routing_id INTEGER NOT NULL REFERENCES technical_routings(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    workcenter_id INTEGER REFERENCES technical_workcenters(id) ON DELETE RESTRICT,
    description TEXT NOT NULL DEFAULT '',
    setup_minutes REAL NOT NULL DEFAULT 0,
    run_minutes REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_technical_routing_steps_routing ON technical_routing_steps(routing_id, position);
"""),
]

KINDS = (
    ("goods", ("Marchandise", "Goods"), "info"), ("raw", ("Matière première", "Raw material"), "outline"),
    ("semi", ("Semi-fini", "Semi-finished"), "outline"), ("finished", ("Produit fini", "Finished product"), "accent"),
    ("service", ("Service", "Service"), "good"),
)
UNITS = (
    ("u", ("Unité", "Unit")), ("lot", ("Lot", "Batch")), ("kg", ("Kilogramme", "Kilogram")), ("g", ("Gramme", "Gram")),
    ("m", ("Mètre", "Metre")), ("m2", ("Mètre carré", "Square metre")), ("m3", ("Mètre cube", "Cubic metre")),
    ("l", ("Litre", "Litre")), ("h", ("Heure", "Hour")), ("feuille", ("Feuille", "Sheet")),
)
VAT_RATES = ((20, ("20 %", "20%")), (10, ("10 %", "10%")), (5.5, ("5,5 %", "5.5%")), (2.1, ("2,1 %", "2.1%")), (0, ("0 %", "0%")))


def _marks(ids: list) -> str:
    return ", ".join("?" for _ in ids)


def _units(ids: list) -> dict[int, str]:
    ids = sorted({i for i in ids if i})
    if not ids:
        return {}
    return {r["id"]: r["unit"] for r in db.fetch_all(f"SELECT id, unit FROM technical_articles WHERE id IN ({_marks(ids)})",
                                                      tuple(ids))}


# ═════════════════════════════════════════════════════════════════════════
# Articles
# ═════════════════════════════════════════════════════════════════════════
def _article_costs(rows: list[dict]) -> None:
    """Coût de revient (achat, ou matière + fabrication) et marge sur le prix de vente."""
    memo: dict = {}
    for row in rows:
        if row.get("id") and row.get("purchase_price") is None:
            cost = cost_price(row["id"], memo)
        else:
            cost = row.get("purchase_price")
        row["cost_price"] = round(cost, 2) if cost is not None else None
        sale = row.get("sale_price")
        row["margin_rate"] = round((sale - cost) / sale * 100, 1) if sale and cost is not None and sale > 0 else None


def _article_validate(values: dict, existing: dict | None) -> None:
    if values.get("kind") == "service" and (values.get("min_stock") or 0) > 0:
        raise ValueError("Un service ne se stocke pas : laissez le stock minimum vide.")


FAMILIES = Entity(
    module="technical", name="families", table="technical_families", label=("Famille", "Family"),
    plural=("Familles d'articles", "Item families"), title="name", order_by="name COLLATE NOCASE", icon="Layers",
    description=("Regroupez vos articles (matières, composants, produits finis…).", "Group your items (materials, parts, products…)."),
    fields=[
        Field("name", ("Nom", "Name"), required=True, unique=True, list=True, search=True, maxlength=80),
        Field("description", ("Description", "Description"), type="longtext", list=True),
    ],
)

ARTICLES = Entity(
    module="technical", name="articles", table="technical_articles", label=("Article", "Item"), plural=("Articles", "Items"),
    title="name", subtitle="code", order_by="name COLLATE NOCASE", icon="Package", active="active",
    description=("Le référentiel commun aux ventes, aux achats, au stock et à la production.",
                 "The shared catalogue for sales, purchasing, stock and production."),
    fields=[
        Field("code", ("Référence", "Reference"), type="code", prefix="ART", yearly=False, readonly=True, list=True, search=True),
        Field("name", ("Désignation", "Name"), required=True, list=True, search=True, maxlength=160),
        Field("kind", ("Type", "Type"), type="enum", choices=KINDS, default="goods", required=True, list=True, filter=True),
        Field("family_id", ("Famille", "Family"), type="ref", ref="technical.families", list=True, filter=True),
        Field("unit", ("Unité", "Unit"), type="enum", choices=UNITS, default="u", required=True),
        Field("sale_price", ("Prix de vente HT", "Sale price excl. VAT"), type="money", min=0, max=1_000_000_000, list=True),
        Field("purchase_price", ("Coût d'achat HT", "Purchase cost excl. VAT"), type="money", min=0, max=1_000_000_000,
              help=("Vide pour un article fabriqué : son coût vient de sa nomenclature et de sa gamme.",
                    "Leave empty for a manufactured item: its cost comes from its bill and routing.")),
        Field("cost_price", ("Coût de revient", "Cost price"), type="money", computed=True, list=True),
        Field("margin_rate", ("Marge", "Margin"), type="percent", computed=True, list=True),
        Field("vat_rate", ("TVA", "VAT"), type="percent", choices=VAT_RATES, default=20),
        Field("min_stock", ("Stock minimum", "Minimum stock"), type="decimal", min=0, max=1_000_000_000,
              help=("En dessous, l'article est signalé à réapprovisionner.", "Below this level, the item is flagged for reordering.")),
        Field("reorder_qty", ("Quantité à commander", "Reorder quantity"), type="decimal", min=0, max=1_000_000_000),
        Field("lead_time_days", ("Délai d'approvisionnement (jours)", "Lead time (days)"), type="int", min=0, max=3650),
        Field("barcode", ("Code-barres", "Barcode"), maxlength=40, search=True),
        Field("active", ("Actif", "Active"), type="bool", default=True, filter=True),
        Field("description", ("Description", "Description"), type="longtext", width="full"),
    ],
    compute=_article_costs, validate=_article_validate,
)


# ═════════════════════════════════════════════════════════════════════════
# Nomenclatures
# ═════════════════════════════════════════════════════════════════════════
def _bom_costs(rows: list[dict]) -> None:
    """Coût matière d'une unité produite : Σ besoin × coût d'achat du composant, ÷ quantité de la nomenclature."""
    missing = [r["id"] for r in rows if "lines" not in r and r.get("id")]
    lines_by_bom: dict[int, list[dict]] = {}
    if missing:
        for line in db.fetch_all(f"SELECT bom_id, article_id, quantity, scrap_rate FROM technical_bom_lines "
                                 f"WHERE bom_id IN ({_marks(missing)})", tuple(missing)):
            lines_by_bom.setdefault(line["bom_id"], []).append(line)
    all_lines = [line for r in rows for line in (r.get("lines") if "lines" in r else lines_by_bom.get(r.get("id"), []))]
    units = _units([line.get("article_id") for line in all_lines])
    memo: dict = {}
    for row in rows:
        lines = row["lines"] if "lines" in row else lines_by_bom.get(row.get("id"), [])
        total = 0.0
        for line in lines:
            # composant acheté : son coût d'achat ; fabriqué : son propre coût de revient, de proche en proche
            price = cost_price(line.get("article_id"), memo)
            line["line_cost"] = round(bom_line_need(line) * price, 2) if price is not None else None
            line["unit"] = units.get(line.get("article_id"))
            total += line["line_cost"] or 0
        quantity = row.get("quantity") or 1
        row["unit_cost"] = round(total / quantity, 2) if quantity > 0 else None
        row["components"] = len(lines)


def _bom_validate(values: dict, existing: dict | None) -> None:
    if (values.get("quantity") or 0) <= 0:
        raise ValueError("Quantité produite : elle doit être positive.")
    article = values.get("article_id")
    components = [line.get("article_id") for line in values.get("lines", []) or []]
    if article and article in components:
        raise ValueError("Un article ne peut pas être son propre composant.")
    # Boucle indirecte : un composant dont la nomenclature contient (de proche en proche) l'article fabriqué
    seen, stack = set(), [c for c in components if c]
    while article and stack:
        current = stack.pop()
        if current == article:
            raise ValueError("Nomenclature circulaire : un composant utilise déjà cet article.")
        if current in seen or len(seen) > 2000:
            continue
        seen.add(current)
        stack += [r["article_id"] for r in db.fetch_all(
            "SELECT l.article_id FROM technical_bom_lines l JOIN technical_boms b ON b.id = l.bom_id "
            "WHERE b.article_id = ? AND b.active = 1 AND l.article_id IS NOT NULL", (current,))]


BOM_LINE_FIELDS = [
    Field("article_id", ("Composant", "Component"), type="ref", ref="technical.articles", required=True),
    Field("quantity", ("Quantité", "Quantity"), type="decimal", default=1, min=0, max=1_000_000_000, required=True),
    Field("unit", ("Unité", "Unit"), type="enum", choices=UNITS, computed=True),
    Field("scrap_rate", ("Pertes", "Scrap"), type="percent", default=0, min=0, max=100),
    Field("line_cost", ("Coût", "Cost"), type="money", computed=True),
    Field("notes", ("Remarque", "Note"), maxlength=200),
]

BOMS = Entity(
    module="technical", name="boms", table="technical_boms", label=("Nomenclature", "Bill of materials"),
    plural=("Nomenclatures", "Bills of materials"), title="code", subtitle="name", icon="ListTree",
    description=("Les composants nécessaires pour fabriquer un article, et le coût matière qui en découle.",
                 "The components needed to make an item, and the resulting material cost."),
    fields=[
        Field("code", ("Numéro", "Number"), type="code", prefix="NOM", yearly=False, readonly=True, list=True, search=True),
        Field("article_id", ("Article fabriqué", "Manufactured item"), type="ref", ref="technical.articles", required=True,
              list=True, filter=True),
        Field("name", ("Libellé", "Label"), list=True, search=True, maxlength=120),
        Field("quantity", ("Quantité produite", "Output quantity"), type="decimal", default=1, min=0, max=1_000_000_000,
              required=True, help=("La nomenclature décrit les composants pour cette quantité.",
                                   "The bill lists the components for this quantity.")),
        Field("unit_cost", ("Coût matière unitaire", "Material cost per unit"), type="money", computed=True, list=True),
        Field("components", ("Composants", "Components"), type="int", computed=True, list=True),
        Field("active", ("Active", "Active"), type="bool", default=True, list=True, filter=True,
              help=("La production utilise la nomenclature active la plus récente de l'article.",
                    "Production uses the item's most recent active bill.")),
        Field("notes", ("Notes", "Notes"), type="longtext", width="full"),
    ],
    children=[Child("lines", ("Composants", "Components"), "technical_bom_lines", "bom_id", BOM_LINE_FIELDS, min_rows=0)],
    compute=_bom_costs, validate=_bom_validate,
)


# ═════════════════════════════════════════════════════════════════════════
# Postes de charge et gammes
# ═════════════════════════════════════════════════════════════════════════
WORKCENTER_KINDS = (("machine", ("Machine", "Machine")), ("manual", ("Poste manuel", "Manual station")),
                    ("subcontracting", ("Sous-traitance", "Subcontracting"), "outline"))

WORKCENTERS = Entity(
    module="technical", name="workcenters", table="technical_workcenters", label=("Poste de charge", "Work centre"),
    plural=("Postes de charge", "Work centres"), title="name", subtitle="code", order_by="name COLLATE NOCASE", icon="Cog",
    active="active",
    description=("Machines et postes de travail, avec leur coût horaire et leur capacité.",
                 "Machines and workstations, with their hourly cost and capacity."),
    fields=[
        Field("code", ("Code", "Code"), type="code", prefix="PC", yearly=False, readonly=True, list=True),
        Field("name", ("Nom", "Name"), required=True, list=True, search=True, maxlength=120),
        Field("kind", ("Type", "Type"), type="enum", choices=WORKCENTER_KINDS, default="machine", required=True, list=True,
              filter=True),
        Field("hourly_cost", ("Coût horaire", "Hourly cost"), type="money", min=0, max=1_000_000, list=True),
        Field("capacity_hours", ("Capacité (h/jour)", "Capacity (h/day)"), type="decimal", min=0, max=24, list=True),
        Field("active", ("Actif", "Active"), type="bool", default=True, filter=True),
        Field("notes", ("Notes", "Notes"), type="longtext", width="full"),
    ],
)


def _routing_totals(rows: list[dict]) -> None:
    """Temps et coût d'une unité : Σ temps unitaire (+ réglage) × coût horaire du poste."""
    missing = [r["id"] for r in rows if "steps" not in r and r.get("id")]
    steps_by_routing: dict[int, list[dict]] = {}
    if missing:
        for step in db.fetch_all(f"SELECT routing_id, workcenter_id, setup_minutes, run_minutes FROM technical_routing_steps "
                                 f"WHERE routing_id IN ({_marks(missing)})", tuple(missing)):
            steps_by_routing.setdefault(step["routing_id"], []).append(step)
    centers = {r["id"]: r["hourly_cost"] for r in db.fetch_all("SELECT id, hourly_cost FROM technical_workcenters")}
    for row in rows:
        steps = row["steps"] if "steps" in row else steps_by_routing.get(row.get("id"), [])
        minutes = cost = setup = 0.0
        for step in steps:
            rate = centers.get(step.get("workcenter_id")) or 0
            run = step.get("run_minutes") or 0
            step["step_cost"] = round(run / 60 * rate, 2)
            minutes += run
            setup += step.get("setup_minutes") or 0
            cost += step["step_cost"]
        row["run_minutes_total"] = round(minutes, 2)
        row["setup_minutes_total"] = round(setup, 2)
        row["unit_cost"] = round(cost, 2)


ROUTING_STEP_FIELDS = [
    Field("workcenter_id", ("Poste", "Work centre"), type="ref", ref="technical.workcenters", required=True),
    Field("description", ("Opération", "Operation"), required=True, maxlength=160),
    Field("setup_minutes", ("Réglage (min)", "Setup (min)"), type="decimal", default=0, min=0, max=100_000),
    Field("run_minutes", ("Temps unitaire (min)", "Run time per unit (min)"), type="decimal", default=0, min=0, max=100_000),
    Field("step_cost", ("Coût unitaire", "Cost per unit"), type="money", computed=True),
]

ROUTINGS = Entity(
    module="technical", name="routings", table="technical_routings", label=("Gamme", "Routing"),
    plural=("Gammes", "Routings"), title="code", subtitle="name", icon="Route",
    description=("Les opérations de fabrication d'un article, poste par poste, avec temps et coûts calculés.",
                 "How an item is made, step by step, with calculated times and costs."),
    fields=[
        Field("code", ("Numéro", "Number"), type="code", prefix="GAM", yearly=False, readonly=True, list=True, search=True),
        Field("article_id", ("Article", "Item"), type="ref", ref="technical.articles", required=True, list=True, filter=True),
        Field("name", ("Libellé", "Label"), list=True, search=True, maxlength=120),
        Field("run_minutes_total", ("Temps unitaire (min)", "Run time per unit (min)"), type="decimal", computed=True, list=True),
        Field("setup_minutes_total", ("Réglages (min)", "Setup (min)"), type="decimal", computed=True),
        Field("unit_cost", ("Coût de fabrication unitaire", "Manufacturing cost per unit"), type="money", computed=True, list=True),
        Field("active", ("Active", "Active"), type="bool", default=True, list=True, filter=True),
        Field("notes", ("Notes", "Notes"), type="longtext", width="full"),
    ],
    children=[Child("steps", ("Opérations", "Operations"), "technical_routing_steps", "routing_id", ROUTING_STEP_FIELDS)],
    compute=_routing_totals,
)

ENTITIES = [ARTICLES, FAMILIES, BOMS, WORKCENTERS, ROUTINGS]
