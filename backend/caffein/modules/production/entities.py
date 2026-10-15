# SPDX-License-Identifier: AGPL-3.0-or-later
"""Entités de la Production : ordres de fabrication et charge des postes.

Un ordre passe de « Brouillon » à « Lancé », puis « Terminé » (ou « Annulé »). En brouillon, ses besoins en composants
et ses opérations sont une prévision, calculée d'après la nomenclature et la gamme actives de l'article. Le lancement
les enregistre avec l'ordre. Terminer l'ordre annonce `production.order_completed` : la Logistique fait entrer le
produit en stock et en sort les composants consommés. Les calculs (besoins, stock disponible, manques, coûts, retard)
viennent de planning.py.
"""

from __future__ import annotations

from ... import db
from ...core import events
from ...core.entities import Action, Child, Entity, Field
from ...core.errors import Conflict
from ...utils import today
from ..stock import services as stock
from ..technical import services as technical
from . import planning

MIGRATIONS = [
    (1, """
-- article_id, warehouse_id, bom_id : fiches des Données techniques et de la Logistique (pas de clé étrangère
-- vers un autre module)
CREATE TABLE IF NOT EXISTS production_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL DEFAULT '',
    article_id INTEGER,
    quantity REAL,
    planned_start TEXT,
    planned_end TEXT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'released', 'done', 'cancelled')),
    warehouse_id INTEGER,
    produced_quantity REAL,
    completed_on TEXT,
    bom_id INTEGER,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_production_orders_code ON production_orders(code) WHERE code != '';
CREATE INDEX IF NOT EXISTS idx_production_orders_status ON production_orders(status, planned_end);
CREATE INDEX IF NOT EXISTS idx_production_orders_article ON production_orders(article_id);

-- Besoins en composants, enregistrés au lancement (article_id : article des Données techniques)
CREATE TABLE IF NOT EXISTS production_order_components (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES production_orders(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    article_id INTEGER,
    quantity REAL
);
CREATE INDEX IF NOT EXISTS idx_production_order_components_order ON production_order_components(order_id, position);
CREATE INDEX IF NOT EXISTS idx_production_order_components_article ON production_order_components(article_id);

-- Opérations, enregistrées au lancement (workcenter_id : poste de charge des Données techniques)
CREATE TABLE IF NOT EXISTS production_order_operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES production_orders(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    workcenter_id INTEGER,
    description TEXT NOT NULL DEFAULT '',
    planned_minutes REAL
);
CREATE INDEX IF NOT EXISTS idx_production_order_operations_order ON production_order_operations(order_id, position);
CREATE INDEX IF NOT EXISTS idx_production_order_operations_workcenter ON production_order_operations(workcenter_id);

-- Charge des postes : heures prévues des ordres lancés, poste par poste (un ordre terminé ou annulé ne charge plus)
CREATE VIEW IF NOT EXISTS production_load AS
    SELECT w.id AS id, w.id AS workcenter_id, w.name AS workcenter_name, w.capacity_hours AS capacity_hours,
           ROUND(COALESCE(r.minutes, 0) / 60.0, 2) AS planned_hours, COALESCE(r.orders, 0) AS orders
    FROM technical_workcenters w
    LEFT JOIN (SELECT op.workcenter_id AS workcenter_id, SUM(op.planned_minutes) AS minutes,
                      COUNT(DISTINCT op.order_id) AS orders
               FROM production_order_operations op JOIN production_orders o ON o.id = op.order_id
               WHERE o.status = 'released' AND op.workcenter_id IS NOT NULL
               GROUP BY op.workcenter_id) r ON r.workcenter_id = w.id;
"""),
]

STATUSES = (
    ("draft", ("Brouillon", "Draft")), ("released", ("Lancé", "Released"), "info"),
    ("done", ("Terminé", "Completed"), "good"), ("cancelled", ("Annulé", "Cancelled"), "outline"),
)
NO_BOM = "Cet article n'a pas de nomenclature active : créez-la dans Données techniques."
SERVICE = "Article à fabriquer : un service ne se fabrique pas."


def _today() -> str:
    return today().isoformat()


def _marks(items: tuple | list) -> str:
    return ", ".join("?" for _ in items)


def _number(value: float) -> str:
    """41.2 → « 41,2 » ; 5.0 → « 5 » (messages en français)."""
    return f"{value:.6f}".rstrip("0").rstrip(".").replace(".", ",")


# ═════════════════════════════════════════════════════════════════════════
# Ordres de fabrication
# ═════════════════════════════════════════════════════════════════════════
def _order_figures(rows: list[dict]) -> None:
    """Besoins, stock disponible, manques, temps, coûts et retard. Brouillon : prévision d'après la nomenclature et
    la gamme actives (les lignes prévues s'affichent dans la fiche, sans être enregistrées). Ordre lancé, terminé ou
    annulé : les lignes enregistrées au lancement, celles de la fiche, sinon une requête groupée pour toute la liste."""
    ctx = planning.Context()
    stored = planning.stored_lines([r.get("id") for r in rows if not planning.is_forecast(r)
                                    and ("components" not in r or "operations" not in r)])
    for row in rows:
        if planning.is_forecast(row):
            components, operations = ctx.forecast(row.get("article_id"), row.get("quantity"))
            if "components" in row or "operations" in row:  # fiche ou aperçu : on montre les lignes prévues
                for line in components:
                    line["article_id__label"] = (ctx.article(line["article_id"]) or {}).get("name")
                for line in operations:
                    line["workcenter_id__label"] = ctx.workcenter(line["workcenter_id"]).get("name")
                row["components"], row["operations"] = components, operations
        else:
            saved = stored.get(row.get("id"), {})
            components = row["components"] if "components" in row else saved.get("components", [])
            operations = row["operations"] if "operations" in row else saved.get("operations", [])
        row.update(planning.figures(row, components, operations, ctx))


def _order_validate(values: dict, existing: dict | None) -> None:
    article_id = values.get("article_id")
    if article_id and (existing is None or article_id != existing.get("article_id")):
        article = technical.article(article_id)
        if article is not None and article["kind"] == "service":
            raise ValueError(SERVICE)
    quantity = values.get("quantity")
    if quantity is not None and quantity <= 0:
        raise ValueError("Quantité : elle doit être positive.")
    start, end = values.get("planned_start"), values.get("planned_end")
    if start and end and end < start:
        raise ValueError("Fin prévue : elle ne peut pas précéder le début prévu.")


def _order_locked(row: dict) -> str | None:
    return {
        "released": "Ordre lancé : il ne se modifie plus. Annulez-le et créez-en un autre si besoin.",
        "done": "Ordre terminé : il ne se modifie plus.",
        "cancelled": "Ordre annulé : il ne se modifie plus.",
    }.get(row.get("status"))


def _order_before_delete(row: dict) -> None:
    if row.get("status") not in ("draft", "cancelled"):
        raise Conflict("Seul un ordre en brouillon ou annulé peut être supprimé.")


def _move(conn, row: dict, status: str, origins: tuple[str, ...], **extra) -> None:
    """Change le statut, seulement depuis l'un des statuts `origins` : deux actions simultanées sur le même ordre
    (double clic, deux personnes) ne passent pas toutes les deux."""
    values = {"status": status, "updated_at": db.now_iso(), **extra}
    sets = ", ".join(f"{name} = ?" for name in values)
    cur = conn.execute(f"UPDATE production_orders SET {sets} WHERE id = ? AND status IN ({_marks(origins)})",
                       (*values.values(), row["id"], *origins))
    if cur.rowcount == 0:
        raise Conflict("L'ordre de fabrication vient d'être modifié par ailleurs : rechargez-le.")


def _shortage_note(row: dict, components: list[dict]) -> str:
    """« Stock insuffisant pour 2 composant(s) : … (il en manque 6,5), … » ou rien."""
    ctx = planning.Context()
    short = []
    for line in components:
        if not ctx.stocked(line["article_id"]):
            continue
        missing = planning.shortage(line["quantity"], ctx.on_hand(line["article_id"], row.get("warehouse_id")))
        if missing > 0:
            short.append(f"{ctx.article(line['article_id'])['name']} (il en manque {_number(missing)})")
    return f"Stock insuffisant pour {len(short)} composant(s) : {', '.join(short)}." if short else ""


def _release(row: dict, payload: dict, user: dict) -> str:
    """Brouillon → lancé : les besoins (nomenclature active) et les opérations (gamme active) sont enregistrés."""
    article = technical.article(row.get("article_id"))
    if article is None:
        raise ValueError("Article à fabriquer : fiche introuvable.")
    if article["kind"] == "service":
        raise ValueError(SERVICE)
    quantity = row.get("quantity")
    if not quantity or quantity <= 0:
        raise ValueError("Quantité : elle doit être positive.")
    bom = technical.active_bom(article["id"])
    if not bom:
        raise ValueError(NO_BOM)
    components = technical.components_for(article["id"], quantity)
    operations = planning.operations(technical.active_routing(article["id"]), quantity)
    with db.connect() as conn:
        _move(conn, row, "released", ("draft",), bom_id=bom["id"])
        for table in ("production_order_components", "production_order_operations"):
            conn.execute(f"DELETE FROM {table} WHERE order_id = ?", (row["id"],))
        conn.executemany("INSERT INTO production_order_components (order_id, position, article_id, quantity) "
                         "VALUES (?, ?, ?, ?)",
                         [(row["id"], i, c["article_id"], c["quantity"]) for i, c in enumerate(components)])
        conn.executemany("INSERT INTO production_order_operations (order_id, position, workcenter_id, description, "
                         "planned_minutes) VALUES (?, ?, ?, ?, ?)",
                         [(row["id"], i, o["workcenter_id"], o["description"], o["planned_minutes"])
                          for i, o in enumerate(operations)])
    return " ".join(m for m in (f"Ordre {row['code']} lancé.", _shortage_note(row, components)) if m)


def _complete(row: dict, payload: dict, user: dict) -> str:
    """Lancé → terminé. La Logistique fait entrer le produit et sortir les composants enregistrés au lancement ;
    une erreur d'un abonné annule la fin de l'ordre (l'événement part avant le changement d'état)."""
    day = _today()
    warehouse = row.get("warehouse_id") or stock.default_warehouse_id()
    components = db.fetch_all("SELECT article_id, quantity FROM production_order_components WHERE order_id = ? "
                              "ORDER BY position, id", (row["id"],))
    messages = events.emit("production.order_completed", {
        "order_id": row["id"], "code": row["code"], "date": day, "article_id": row["article_id"],
        "quantity": row["quantity"], "warehouse_id": warehouse, "components": components,
    })
    with db.connect() as conn:
        _move(conn, row, "done", ("released",), produced_quantity=row["quantity"], completed_on=day, warehouse_id=warehouse)
    return " ".join([f"Ordre {row['code']} terminé.", *messages])


def _cancel(row: dict, payload: dict, user: dict) -> str:
    with db.connect() as conn:
        _move(conn, row, "cancelled", ("draft", "released"))
    return f"Ordre {row['code']} annulé."


COMPONENT_FIELDS = [
    Field("article_id", ("Composant", "Component"), type="ref", ref="technical.articles", readonly=True),
    Field("quantity", ("Besoin", "Required"), type="decimal", readonly=True),
    Field("available", ("En stock", "On hand"), type="decimal", computed=True),
    Field("shortage", ("Manquant", "Shortage"), type="decimal", computed=True),
]

OPERATION_FIELDS = [
    Field("workcenter_id", ("Poste", "Work centre"), type="ref", ref="technical.workcenters", readonly=True),
    Field("description", ("Opération", "Operation"), readonly=True),
    Field("planned_minutes", ("Temps prévu (min)", "Planned time (min)"), type="decimal", readonly=True),
    Field("cost", ("Coût", "Cost"), type="money", computed=True),
]

ORDERS = Entity(
    module="production", name="orders", table="production_orders", label=("Ordre de fabrication", "Manufacturing order"),
    plural=("Ordres de fabrication", "Manufacturing orders"), title="code", order_by="id DESC", icon="Factory",
    board="status",
    description=("Lancez la fabrication d'un article : besoins en composants, manques, temps et coûts sont calculés ; "
                 "terminer l'ordre met le stock à jour.",
                 "Release the production of an item: component needs, shortages, times and costs are calculated; "
                 "completing the order updates the stock."),
    fields=[
        Field("code", ("Numéro", "Number"), type="code", prefix="OF", readonly=True, list=True, search=True),
        Field("article_id", ("Article à fabriquer", "Item to make"), type="ref", ref="technical.articles", required=True,
              list=True, filter=True),
        Field("quantity", ("Quantité", "Quantity"), type="decimal", required=True, max=1_000_000_000, list=True),
        Field("planned_start", ("Début prévu", "Planned start"), type="date", default=_today, list=True),
        Field("planned_end", ("Fin prévue", "Planned end"), type="date", list=True),
        Field("status", ("Statut", "Status"), type="enum", choices=STATUSES, default="draft", readonly=True, list=True,
              filter=True),
        Field("warehouse_id", ("Entrepôt", "Warehouse"), type="ref", ref="stock.warehouses",
              help=("Où le produit entre en stock et où les composants sont consommés ; vide : l'entrepôt par défaut. "
                    "Le stock disponible des composants est celui de cet entrepôt, ou de tous les entrepôts s'il est vide.",
                    "Where the product goes into stock and components are consumed; empty: the default warehouse. "
                    "Component availability is read from this warehouse, or from all warehouses when empty.")),
        Field("produced_quantity", ("Quantité produite", "Quantity produced"), type="decimal", readonly=True),
        Field("completed_on", ("Terminé le", "Completed on"), type="date", readonly=True),
        Field("material_cost", ("Coût matière", "Material cost"), type="money", computed=True,
              help=("Besoins × coût de revient des composants.", "Needs × component cost price.")),
        Field("labour_cost", ("Coût des opérations", "Operations cost"), type="money", computed=True,
              help=("Temps prévus × coût horaire des postes.", "Planned times × work centre hourly cost.")),
        Field("total_cost", ("Coût total", "Total cost"), type="money", computed=True),
        Field("unit_cost", ("Coût unitaire", "Unit cost"), type="money", computed=True),
        Field("shortages", ("Composants manquants", "Missing components"), type="int", computed=True, list=True,
              help=("Composants dont le stock ne couvre pas le besoin.", "Components whose stock does not cover the need.")),
        Field("late", ("En retard", "Late"), type="bool", computed=True, list=True),
        Field("bom_id", ("Nomenclature", "Bill of materials"), type="int", readonly=True, hidden=True),
        Field("notes", ("Notes", "Notes"), type="longtext", width="full"),
    ],
    children=[
        Child("components", ("Composants", "Components"), "production_order_components", "order_id", COMPONENT_FIELDS),
        Child("operations", ("Opérations", "Operations"), "production_order_operations", "order_id", OPERATION_FIELDS),
    ],
    actions=[
        Action("release", ("Lancer", "Release"), _release, when=lambda r: r["status"] == "draft", style="primary",
               icon="Play"),
        Action("complete", ("Terminer", "Complete"), _complete, when=lambda r: r["status"] == "released", style="primary",
               icon="PackageCheck",
               confirm=("Terminer l'ordre ? Le produit entre en stock et les composants en sortent : c'est définitif.",
                        "Complete the order? The product goes into stock and the components are consumed: "
                        "this cannot be undone.")),
        Action("cancel", ("Annuler", "Cancel"), _cancel, when=lambda r: r["status"] in ("draft", "released"),
               style="danger", icon="Ban", confirm=("Annuler cet ordre de fabrication ?", "Cancel this manufacturing order?")),
    ],
    compute=_order_figures, validate=_order_validate, locked=_order_locked, before_delete=_order_before_delete,
)


# ═════════════════════════════════════════════════════════════════════════
# Charge des postes (vue SQL, consultation)
# ═════════════════════════════════════════════════════════════════════════
def _load_days(rows: list[dict]) -> None:
    """Charge en jours : heures prévues ÷ capacité journalière du poste (rien sans capacité)."""
    for row in rows:
        capacity = row.get("capacity_hours")
        row["load_days"] = round((row.get("planned_hours") or 0) / capacity, 2) if capacity and capacity > 0 else None


LOAD = Entity(
    module="production", name="load", table="production_load", label=("Charge d'un poste", "Work centre load"),
    plural=("Charge des postes", "Work centre load"), title="workcenter_name", order_by="workcenter_name COLLATE NOCASE",
    icon="Gauge", readonly=True,
    description=("Les heures prévues des ordres lancés, poste par poste, rapportées à la capacité journalière.",
                 "Planned hours of released orders, by work centre, against daily capacity."),
    fields=[
        Field("workcenter_name", ("Poste", "Work centre"), list=True, search=True),
        Field("workcenter_id", ("Fiche du poste", "Work centre record"), type="ref", ref="technical.workcenters"),
        Field("capacity_hours", ("Capacité (h/jour)", "Capacity (h/day)"), type="decimal", list=True),
        Field("planned_hours", ("Heures prévues", "Planned hours"), type="decimal", list=True,
              help=("Opérations des ordres lancés : réglage + temps unitaire × quantité.",
                    "Operations of released orders: setup + run time × quantity.")),
        Field("orders", ("Ordres lancés", "Released orders"), type="int", list=True),
        Field("load_days", ("Charge (jours)", "Load (days)"), type="decimal", computed=True, list=True,
              help=("Heures prévues ÷ capacité journalière.", "Planned hours ÷ daily capacity.")),
    ],
    compute=_load_days,
)

ENTITIES = [ORDERS, LOAD]

# Nomenclature utilisée au lancement (champ caché de l'ordre) : elle ne se supprime pas tant qu'un ordre la désigne
REFERENCES = [("production_orders", "bom_id", "technical.boms", ("Ordres de fabrication", "Manufacturing orders"))]
