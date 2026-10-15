# SPDX-License-Identifier: AGPL-3.0-or-later
"""Entités des Achats : fournisseurs et commandes fournisseurs.

Une commande passe de « Brouillon » à « Envoyée », puis « Reçue » (ou « Annulée »). La réception annonce
`purchases.order_received` : la Logistique, si elle est active, fait entrer les articles en stock au prix d'achat.
Les montants (lignes, HT, TVA, TTC), les retards et les chiffres des fournisseurs viennent de figures.py.
"""

from __future__ import annotations

import re
from datetime import date

from ... import db
from ...core import events
from ...core.entities import Action, Child, Entity, Field
from ...core.errors import Conflict
from ...utils import parse_date, today
from .figures import LINE_DEFAULTS, is_late, lines_by_order, placed_between, totals

MIGRATIONS = [
    (1, """
CREATE TABLE IF NOT EXISTS purchases_suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    contact_name TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    zip_code TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    country TEXT NOT NULL DEFAULT '',
    siren TEXT NOT NULL DEFAULT '',
    vat_number TEXT NOT NULL DEFAULT '',
    payment_terms_days INTEGER,
    notes TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_purchases_suppliers_code ON purchases_suppliers(code) WHERE code != '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_purchases_suppliers_name ON purchases_suppliers(name COLLATE NOCASE);

-- warehouse_id : entrepôt de la Logistique, facultatif (pas de clé étrangère vers un autre module)
CREATE TABLE IF NOT EXISTS purchases_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL DEFAULT '',
    supplier_id INTEGER REFERENCES purchases_suppliers(id) ON DELETE RESTRICT,
    order_date TEXT,
    expected_date TEXT,
    received_date TEXT,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'sent', 'received', 'cancelled')),
    warehouse_id INTEGER,
    supplier_ref TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_purchases_orders_code ON purchases_orders(code) WHERE code != '';
CREATE INDEX IF NOT EXISTS idx_purchases_orders_supplier ON purchases_orders(supplier_id);
CREATE INDEX IF NOT EXISTS idx_purchases_orders_status ON purchases_orders(status, order_date);

-- article_id : article des Données techniques, facultatif (pas de clé étrangère vers un autre module)
CREATE TABLE IF NOT EXISTS purchases_order_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES purchases_orders(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    article_id INTEGER,
    description TEXT NOT NULL DEFAULT '',
    quantity REAL,
    unit_price REAL,
    vat_rate REAL
);
CREATE INDEX IF NOT EXISTS idx_purchases_order_lines_order ON purchases_order_lines(order_id, position);
CREATE INDEX IF NOT EXISTS idx_purchases_order_lines_article ON purchases_order_lines(article_id);
"""),
]

STATUSES = (
    ("draft", ("Brouillon", "Draft")), ("sent", ("Envoyée", "Sent"), "info"),
    ("received", ("Reçue", "Received"), "good"), ("cancelled", ("Annulée", "Cancelled"), "outline"),
)
VAT_RATES = ((20, ("20 %", "20%")), (10, ("10 %", "10%")), (5.5, ("5,5 %", "5.5%")), (2.1, ("2,1 %", "2.1%")), (0, ("0 %", "0%")))


def _today() -> str:
    return today().isoformat()


def _marks(ids: list) -> str:
    return ", ".join("?" for _ in ids)


# ═════════════════════════════════════════════════════════════════════════
# Fournisseurs
# ═════════════════════════════════════════════════════════════════════════
def _supplier_figures(rows: list[dict]) -> None:
    """Commandes non annulées et montant HT commandé depuis le 1er janvier (commandes envoyées ou reçues)."""
    ids = [r["id"] for r in rows if r.get("id")]
    counts: dict[int, int] = {}
    ordered: dict[int, dict] = {}
    if ids:
        counts = {r["supplier_id"]: r["n"] for r in db.fetch_all(
            f"SELECT supplier_id, COUNT(*) AS n FROM purchases_orders WHERE supplier_id IN ({_marks(ids)}) "
            f"AND status != 'cancelled' GROUP BY supplier_id", tuple(ids))}
        year = today().year
        ordered = placed_between(date(year, 1, 1), date(year + 1, 1, 1), ids)
    for row in rows:
        if not row.get("id"):  # fiche en cours de création : rien à compter
            row["orders_count"] = row["ordered_ytd"] = None
            continue
        row["orders_count"] = counts.get(row["id"], 0)
        row["ordered_ytd"] = ordered.get(row["id"], {}).get("total_ht", 0.0)


def _supplier_prepare(values: dict, existing: dict | None) -> None:
    """Identifiants sans espaces (« 512 345 678 » → « 512345678 »), numéro de TVA en majuscules."""
    if values.get("siren"):
        values["siren"] = re.sub(r"\s", "", values["siren"])
    if values.get("vat_number"):
        values["vat_number"] = re.sub(r"\s", "", values["vat_number"]).upper()


def _supplier_validate(values: dict, existing: dict | None) -> None:
    if values.get("siren") and not re.fullmatch(r"[0-9]{9}", values["siren"]):
        raise ValueError("SIREN : 9 chiffres attendus.")


SUPPLIERS = Entity(
    module="purchases", name="suppliers", table="purchases_suppliers", label=("Fournisseur", "Supplier"),
    plural=("Fournisseurs", "Suppliers"), title="name", subtitle="city", order_by="name COLLATE NOCASE", icon="Truck",
    description=("Vos fournisseurs, leurs coordonnées et leurs conditions de paiement.",
                 "Your suppliers, their contact details and payment terms."),
    fields=[
        Field("code", ("Code", "Code"), type="code", prefix="FRN", yearly=False, readonly=True, list=True),
        Field("name", ("Nom", "Name"), required=True, unique=True, list=True, search=True, maxlength=120),
        Field("contact_name", ("Contact", "Contact"), maxlength=120),
        Field("email", ("Email", "Email"), type="email", list=True),
        Field("phone", ("Téléphone", "Phone"), type="phone"),
        Field("address", ("Adresse", "Address"), width="full", maxlength=240),
        Field("zip_code", ("Code postal", "Postcode"), maxlength=20),
        Field("city", ("Ville", "City"), list=True, search=True, maxlength=120),
        Field("country", ("Pays", "Country"), default="France", maxlength=60),
        Field("siren", ("SIREN", "Company number (SIREN)"), maxlength=20),
        Field("vat_number", ("N° de TVA intracommunautaire", "VAT number"), maxlength=30),
        Field("payment_terms_days", ("Délai de paiement (jours)", "Payment terms (days)"), type="int", default=30, min=0,
              max=120),
        Field("orders_count", ("Commandes", "Orders"), type="int", computed=True, list=True,
              help=("Toutes ses commandes, brouillons compris, sauf les commandes annulées.",
                    "All orders, drafts included, except cancelled ones.")),
        Field("ordered_ytd", ("Commandé cette année HT", "Ordered this year excl. VAT"), type="money", computed=True, list=True,
              help=("Commandes envoyées ou reçues datées de cette année.", "Sent or received orders dated this year.")),
        Field("active", ("Actif", "Active"), type="bool", default=True, filter=True,
              help=("Un fournisseur inactif ne reçoit plus de nouvelles commandes.", "An inactive supplier gets no new orders.")),
        Field("notes", ("Notes", "Notes"), type="longtext", width="full"),
    ],
    compute=_supplier_figures, prepare=_supplier_prepare, validate=_supplier_validate,
)


# ═════════════════════════════════════════════════════════════════════════
# Commandes fournisseurs
# ═════════════════════════════════════════════════════════════════════════
def _order_figures(rows: list[dict]) -> None:
    """Montants HT, TVA et TTC, et retard : depuis les lignes de la fiche (fiche, saisie en cours), sinon par une
    seule requête sur les lignes de toutes les commandes de la liste."""
    stored = lines_by_order([r["id"] for r in rows if "lines" not in r and r.get("id")])
    for row in rows:
        if "lines" in row:
            row.update(totals(row["lines"], annotate=True))
        else:
            row.update(totals(stored.get(row.get("id"), [])))
        row["late"] = is_late(row)


def _order_validate(values: dict, existing: dict | None) -> None:
    ordered, expected = values.get("order_date"), values.get("expected_date")
    if ordered and expected and expected < ordered:
        raise ValueError("Livraison prévue : elle ne peut pas précéder la date de commande.")
    for i, line in enumerate(values.get("lines") or [], start=1):
        if (line.get("quantity") or 0) <= 0:
            raise ValueError(f"Lignes, ligne {i} — Quantité : elle doit être positive.")
    supplier = values.get("supplier_id")
    if supplier and (existing is None or supplier != existing.get("supplier_id")):
        row = db.fetch_one("SELECT active FROM purchases_suppliers WHERE id = ?", (supplier,))
        if row is not None and not row["active"]:
            raise ValueError("Fournisseur : ce fournisseur est inactif ; réactivez-le dans sa fiche pour lui passer commande.")


def _order_locked(row: dict) -> str | None:
    return {
        "sent": "Commande envoyée : elle ne se modifie plus. Annulez-la et créez-en une autre si besoin.",
        "received": "Commande reçue : elle ne se modifie plus.",
        "cancelled": "Commande annulée : elle ne se modifie plus.",
    }.get(row.get("status"))


def _order_before_delete(row: dict) -> None:
    if row["status"] not in ("draft", "cancelled"):
        raise Conflict("Seule une commande en brouillon ou annulée peut être supprimée.")


def _lines(order_id: int) -> list[dict]:
    return db.fetch_all("SELECT article_id, description, quantity, unit_price FROM purchases_order_lines WHERE order_id = ? "
                        "ORDER BY position, id", (order_id,))


def _move(row: dict, status: str, origins: tuple[str, ...], **extra) -> None:
    """Change le statut, seulement depuis l'un des statuts `origins` : deux actions simultanées sur la même
    commande (double clic, deux personnes) ne passent pas toutes les deux."""
    values = {"status": status, "updated_at": db.now_iso(), **extra}
    sets = ", ".join(f"{name} = ?" for name in values)
    with db.connect() as conn:
        cur = conn.execute(f"UPDATE purchases_orders SET {sets} WHERE id = ? AND status IN ({_marks(origins)})",
                           (*values.values(), row["id"], *origins))
        if cur.rowcount == 0:
            raise Conflict("La commande vient d'être modifiée par ailleurs : rechargez-la.")


def _receipt_date(payload: dict, row: dict) -> str:
    """Date de réception : celle du jour, ou celle indiquée (réception saisie après coup), ni dans le futur,
    ni avant la date de commande."""
    value = payload.get("date")
    if value in (None, ""):
        return _today()
    day = parse_date(value) if isinstance(value, (str, date)) else None
    if day is None:
        raise ValueError("Date de réception : date invalide.")
    if day > today():
        raise ValueError("Date de réception : elle ne peut pas être dans le futur.")
    if row.get("order_date") and day.isoformat() < row["order_date"]:
        raise ValueError("Date de réception : elle ne peut pas précéder la date de commande.")
    return day.isoformat()


def _send(row: dict, payload: dict, user: dict) -> str:
    if not row.get("lines"):
        raise ValueError("Lignes : ajoutez au moins une ligne avant d'envoyer la commande.")
    supplier = db.fetch_one("SELECT active FROM purchases_suppliers WHERE id = ?", (row.get("supplier_id"),))
    if supplier is not None and not supplier["active"]:
        raise ValueError("Fournisseur : ce fournisseur est inactif ; réactivez-le dans sa fiche pour lui envoyer la commande.")
    ordered = row.get("order_date") or _today()  # sans date de commande : celle de l'envoi
    if row.get("expected_date") and row["expected_date"] < ordered:
        raise ValueError("Livraison prévue : elle ne peut pas précéder la date de commande.")
    _move(row, "sent", ("draft",), order_date=ordered)
    return f"Commande {row['code']} envoyée."


def _receive(row: dict, payload: dict, user: dict) -> str:
    day = _receipt_date(payload, row)
    # La Logistique, si elle est active, fait entrer les articles en stock ; une erreur annule la réception
    messages = events.emit("purchases.order_received", {
        "order_id": row["id"], "code": row["code"], "date": day, "warehouse_id": row.get("warehouse_id"),
        "lines": _lines(row["id"]),
    })
    _move(row, "received", ("sent",), received_date=day)
    return " ".join([f"Commande {row['code']} réceptionnée.", *messages])


def _cancel(row: dict, payload: dict, user: dict) -> str:
    _move(row, "cancelled", ("draft", "sent"))
    return f"Commande {row['code']} annulée."


ORDER_LINE_FIELDS = [
    Field("article_id", ("Article", "Item"), type="ref", ref="technical.articles",
          fill={"description": "name", "unit_price": "purchase_price"}),
    Field("description", ("Désignation", "Description"), required=True, maxlength=300, width="full"),
    Field("quantity", ("Quantité", "Quantity"), type="decimal", default=LINE_DEFAULTS["quantity"], required=True,
          max=1_000_000_000),
    Field("unit_price", ("Prix unitaire HT", "Unit price excl. VAT"), type="money", default=LINE_DEFAULTS["unit_price"],
          required=True, min=0, max=1_000_000_000),
    Field("vat_rate", ("TVA", "VAT"), type="percent", choices=VAT_RATES, default=LINE_DEFAULTS["vat_rate"], required=True),
    Field("amount", ("Montant HT", "Amount excl. VAT"), type="money", computed=True),
]

ORDERS = Entity(
    module="purchases", name="orders", table="purchases_orders", label=("Commande fournisseur", "Purchase order"),
    plural=("Commandes fournisseurs", "Purchase orders"), title="code", order_by="id DESC", icon="ShoppingCart",
    description=("Envoyez vos commandes, suivez les livraisons attendues et réceptionnez-les : le stock suit si la "
                 "Logistique est active.",
                 "Send your orders, track expected deliveries and receive them: stock follows when Logistics is on."),
    fields=[
        Field("code", ("Numéro", "Number"), type="code", prefix="CF", readonly=True, list=True, search=True),
        Field("supplier_id", ("Fournisseur", "Supplier"), type="ref", ref="purchases.suppliers", required=True, list=True,
              filter=True),
        Field("order_date", ("Date de commande", "Order date"), type="date", default=_today, list=True),
        Field("expected_date", ("Livraison prévue", "Expected delivery"), type="date", list=True),
        Field("received_date", ("Date de réception", "Received on"), type="date", readonly=True),
        Field("status", ("Statut", "Status"), type="enum", choices=STATUSES, default="draft", readonly=True, list=True,
              filter=True),
        Field("warehouse_id", ("Entrepôt de réception", "Receiving warehouse"), type="ref", ref="stock.warehouses",
              help=("Vide : l'entrepôt par défaut de la Logistique.", "Empty: the default Logistics warehouse.")),
        Field("supplier_ref", ("Référence fournisseur", "Supplier reference"), search=True, maxlength=80,
              help=("Numéro de devis ou de confirmation du fournisseur.", "The supplier's quote or confirmation number.")),
        Field("total_ht", ("Montant HT", "Amount excl. VAT"), type="money", computed=True, list=True),
        Field("total_vat", ("TVA", "VAT"), type="money", computed=True),
        Field("total_ttc", ("Montant TTC", "Amount incl. VAT"), type="money", computed=True),
        Field("late", ("En retard", "Late"), type="bool", computed=True, list=True),
        Field("notes", ("Notes", "Notes"), type="longtext", width="full"),
    ],
    children=[Child("lines", ("Lignes", "Lines"), "purchases_order_lines", "order_id", ORDER_LINE_FIELDS)],
    actions=[
        Action("send", ("Marquer comme envoyée", "Mark as sent"), _send, when=lambda r: r["status"] == "draft",
               style="primary", icon="Send"),
        Action("receive", ("Réceptionner", "Receive"), _receive, when=lambda r: r["status"] == "sent", style="primary",
               icon="PackageCheck", confirm=("Réceptionner la commande ? La réception est définitive.",
                                             "Receive the order? This cannot be undone.")),
        Action("cancel", ("Annuler", "Cancel"), _cancel, when=lambda r: r["status"] in ("draft", "sent"), style="danger",
               icon="Ban", confirm=("Annuler cette commande ?", "Cancel this order?")),
    ],
    compute=_order_figures, validate=_order_validate, locked=_order_locked, before_delete=_order_before_delete,
)

ENTITIES = [ORDERS, SUPPLIERS]
