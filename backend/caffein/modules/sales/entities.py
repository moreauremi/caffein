# SPDX-License-Identifier: AGPL-3.0-or-later
"""Entités des Ventes : clients et commandes clients (les factures et devis ont leur écran sur mesure)."""

from __future__ import annotations

from ... import db, services
from ...core import events
from ...core.entities import Action, Child, Entity, Field
from ...core.errors import Conflict
from ...core.modules import WRITE
from ...utils import cents, today

MIGRATIONS = [
    (1, """
CREATE TABLE IF NOT EXISTS sales_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL DEFAULT '',
    client_id INTEGER REFERENCES clients(id) ON DELETE RESTRICT,
    order_date TEXT,
    delivery_date TEXT,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'confirmed', 'delivered', 'invoiced', 'cancelled')),
    customer_ref TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    invoice_id INTEGER REFERENCES invoices(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_orders_code ON sales_orders(code) WHERE code != '';
CREATE INDEX IF NOT EXISTS idx_sales_orders_status ON sales_orders(status);

-- article_id : article des Données techniques, facultatif (pas de clé étrangère vers un autre module)
CREATE TABLE IF NOT EXISTS sales_order_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES sales_orders(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    article_id INTEGER,
    description TEXT NOT NULL DEFAULT '',
    quantity REAL NOT NULL DEFAULT 1,
    unit_price REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sales_order_lines_order ON sales_order_lines(order_id, position);
"""),
]


def _marks(ids: list) -> str:
    return ", ".join("?" for _ in ids)


# ═════════════════════════════════════════════════════════════════════════
# Clients (table historique `clients`, partagée avec les factures)
# ═════════════════════════════════════════════════════════════════════════
def _client_totals(rows: list[dict]) -> None:
    ids = [r["id"] for r in rows if r.get("id")]
    stats = {}
    if ids:
        stats = {r["client_id"]: r for r in db.fetch_all(f"""
            SELECT client_id,
                   COUNT(*) FILTER (WHERE kind = 'invoice' AND status != 'draft') AS invoice_count,
                   COALESCE(SUM(total) FILTER (WHERE kind = 'invoice' AND status = 'paid'), 0) AS total_paid
            FROM invoices WHERE client_id IN ({_marks(ids)}) GROUP BY client_id""", tuple(ids))}
    for row in rows:
        s = stats.get(row.get("id"), {})
        row["invoice_count"] = s.get("invoice_count", 0)
        row["total_paid"] = cents(s.get("total_paid", 0) or 0)


def _client_before_delete(row: dict) -> None:
    used = db.fetch_one("SELECT COUNT(*) AS n FROM invoices WHERE client_id = ? AND status != 'draft'", (row["id"],))
    if used["n"]:
        raise Conflict("Ce client a des factures émises : il ne peut pas être supprimé.")


CLIENTS = Entity(
    module="sales", name="clients", table="clients", label=("Client", "Customer"), plural=("Clients", "Customers"),
    title="name", subtitle="city", order_by="name COLLATE NOCASE", icon="Building2",
    description=("Vos clients, partagés avec les factures, les devis et les commandes.",
                 "Your customers, shared with invoices, quotes and orders."),
    fields=[
        Field("name", ("Nom", "Name"), required=True, list=True, search=True),
        Field("contact_name", ("Contact", "Contact"), list=True, search=True),
        Field("email", ("Email", "Email"), type="email", list=True, search=True),
        Field("phone", ("Téléphone", "Phone"), type="phone"),
        Field("address", ("Adresse", "Address"), width="full"),
        Field("zip_code", ("Code postal", "Postcode"), maxlength=20),
        Field("city", ("Ville", "City"), list=True, search=True),
        Field("siren", ("SIREN", "Company number"), maxlength=20),
        Field("vat_number", ("N° de TVA", "VAT number"), maxlength=30),
        Field("notes", ("Notes", "Notes"), type="longtext", width="full"),
        Field("invoice_count", ("Factures émises", "Issued invoices"), type="int", computed=True, list=True),
        Field("total_paid", ("Encaissé TTC", "Collected (incl. VAT)"), type="money", computed=True, list=True),
    ],
    compute=_client_totals, before_delete=_client_before_delete,
    delete_level=WRITE,  # comme avant les modules : un client sans facture émise se supprime
)


# ═════════════════════════════════════════════════════════════════════════
# Commandes clients
# ═════════════════════════════════════════════════════════════════════════
ORDER_STATUSES = (
    ("draft", ("Brouillon", "Draft")), ("confirmed", ("Confirmée", "Confirmed"), "info"),
    ("delivered", ("Livrée", "Delivered"), "accent"), ("invoiced", ("Facturée", "Invoiced"), "good"),
    ("cancelled", ("Annulée", "Cancelled"), "outline"),
)


def _today() -> str:
    return today().isoformat()


def _order_totals(rows: list[dict]) -> None:
    """Montant HT : depuis les lignes de la fiche (fiche, saisie en cours), sinon par une requête groupée (liste)."""
    missing = [r["id"] for r in rows if "lines" not in r and r.get("id")]
    sums = {}
    if missing:
        sums = {r["order_id"]: r["total"] for r in db.fetch_all(
            f"SELECT order_id, ROUND(SUM(ROUND(quantity * unit_price, 2)), 2) AS total FROM sales_order_lines "
            f"WHERE order_id IN ({_marks(missing)}) GROUP BY order_id", tuple(missing))}
    invoices = {}
    ids = [r["invoice_id"] for r in rows if r.get("invoice_id")]
    if ids:
        invoices = {r["id"]: r["number"] or "brouillon" for r in
                    db.fetch_all(f"SELECT id, number FROM invoices WHERE id IN ({_marks(ids)})", tuple(ids))}
    for row in rows:
        if "lines" in row:
            for line in row["lines"]:
                line["amount"] = services.line_amount(line)
            row["total_ht"] = cents(sum(line["amount"] for line in row["lines"]))
        else:
            row["total_ht"] = cents(sums.get(row.get("id"), 0) or 0)
        row["invoice_number"] = invoices.get(row.get("invoice_id"), "")


def _order_locked(row: dict) -> str | None:
    if row.get("status") != "draft":
        return "Commande confirmée : elle ne se modifie plus. Annulez-la et créez-en une autre si besoin."
    return None


def _order_before_delete(row: dict) -> None:
    if row["status"] not in ("draft", "cancelled"):
        raise Conflict("Seule une commande en brouillon ou annulée peut être supprimée.")


def _set_status(order_id: int, status: str, **extra) -> None:
    db.update("sales_orders", order_id, {"status": status, "updated_at": db.now_iso(), **extra})


def _lines(order_id: int) -> list[dict]:
    return db.fetch_all("SELECT article_id, description, quantity, unit_price FROM sales_order_lines WHERE order_id = ? "
                        "ORDER BY position, id", (order_id,))


def _confirm(row: dict, payload: dict, user: dict) -> str:
    if not row.get("client_id"):
        raise ValueError("Choisissez un client avant de confirmer la commande.")
    if not row.get("lines"):
        raise ValueError("Ajoutez au moins une ligne avant de confirmer la commande.")
    _set_status(row["id"], "confirmed", order_date=row.get("order_date") or _today())
    events.emit("sales.order_confirmed", {"order_id": row["id"], "code": row["code"], "lines": _lines(row["id"])})
    return f"Commande {row['code']} confirmée."


def _deliver(row: dict, payload: dict, user: dict) -> str:
    date = row.get("delivery_date") or _today()
    # La Logistique, si elle est active, sort les articles du stock ; une erreur annule la livraison
    messages = events.emit("sales.order_delivered", {"order_id": row["id"], "code": row["code"], "date": date,
                                                     "lines": _lines(row["id"])})
    _set_status(row["id"], "delivered", delivery_date=date)
    return " ".join([f"Commande {row['code']} livrée.", *messages])


def _invoice(row: dict, payload: dict, user: dict) -> str:
    invoice = services.create_invoice({
        "kind": "invoice", "client_id": row["client_id"], "title": f"Commande {row['code']}",
        "items": _lines(row["id"]), "delivery_date": row.get("delivery_date"),
        "notes": f"Commande n° {row['code']}" + (f" — votre référence : {row['customer_ref']}" if row.get("customer_ref") else ""),
    })
    _set_status(row["id"], "invoiced", invoice_id=invoice["id"])
    return "Facture brouillon créée : vérifiez-la puis émettez-la dans Factures et devis."


def _cancel(row: dict, payload: dict, user: dict) -> str:
    _set_status(row["id"], "cancelled")
    return f"Commande {row['code']} annulée."


ORDER_LINE_FIELDS = [
    Field("article_id", ("Article", "Item"), type="ref", ref="technical.articles",
          fill={"description": "name", "unit_price": "sale_price"}),
    Field("description", ("Désignation", "Description"), required=True, maxlength=300, width="full"),
    Field("quantity", ("Quantité", "Quantity"), type="decimal", default=1, min=0, max=1_000_000_000),
    Field("unit_price", ("Prix unitaire HT", "Unit price excl. VAT"), type="money", default=0, min=-1_000_000_000,
          max=1_000_000_000),
    Field("amount", ("Montant HT", "Amount excl. VAT"), type="money", computed=True),
]

ORDERS = Entity(
    module="sales", name="orders", table="sales_orders", label=("Commande client", "Sales order"),
    plural=("Commandes clients", "Sales orders"), title="code", order_by="id DESC", icon="ShoppingBag", board="status",
    description=("Confirmez, livrez (sortie de stock si la Logistique est active) puis facturez en un clic.",
                 "Confirm, deliver (stock is updated when Logistics is on) then invoice in one click."),
    fields=[
        Field("code", ("Numéro", "Number"), type="code", prefix="CC", readonly=True, list=True, search=True),
        Field("client_id", ("Client", "Customer"), type="ref", ref="sales.clients", required=True, list=True, filter=True),
        Field("order_date", ("Date de commande", "Order date"), type="date", default=_today, list=True),
        Field("delivery_date", ("Livraison prévue", "Planned delivery"), type="date", list=True),
        Field("status", ("Statut", "Status"), type="enum", choices=ORDER_STATUSES, default="draft", readonly=True,
              list=True, filter=True),
        Field("customer_ref", ("Référence client", "Customer reference"), search=True),
        Field("total_ht", ("Montant HT", "Amount excl. VAT"), type="money", computed=True, list=True),
        Field("invoice_number", ("Facture", "Invoice"), computed=True),
        Field("invoice_id", ("Facture", "Invoice"), type="int", readonly=True, hidden=True),
        Field("notes", ("Notes", "Notes"), type="longtext", width="full"),
    ],
    children=[Child("lines", ("Lignes", "Lines"), "sales_order_lines", "order_id", ORDER_LINE_FIELDS)],
    actions=[
        Action("confirm", ("Confirmer", "Confirm"), _confirm, when=lambda r: r["status"] == "draft", style="primary",
               icon="CheckCircle2"),
        Action("deliver", ("Livrer", "Deliver"), _deliver, when=lambda r: r["status"] == "confirmed", style="primary",
               icon="Truck", confirm=("Marquer la commande comme livrée ?", "Mark the order as delivered?")),
        Action("invoice", ("Facturer", "Invoice"), _invoice,
               when=lambda r: r["status"] in ("confirmed", "delivered") and not r.get("invoice_id"), icon="ReceiptText"),
        Action("cancel", ("Annuler", "Cancel"), _cancel, when=lambda r: r["status"] in ("draft", "confirmed"),
               style="danger", icon="Ban", confirm=("Annuler cette commande ?", "Cancel this order?")),
    ],
    compute=_order_totals, locked=_order_locked, before_delete=_order_before_delete,
)

ENTITIES = [CLIENTS, ORDERS]

# Lignes de factures et de devis (écran sur mesure) : un article utilisé ne se supprime pas
REFERENCES = [("invoice_lines", "article_id", "technical.articles", ("Factures et devis", "Invoices and quotes"))]
