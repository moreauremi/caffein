# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ventes : clients, devis et factures (écran historique de Caffein), commandes clients."""

from __future__ import annotations

from ... import db, services
from ...core.modules import Kpi, Module, Page, Shortcut
from . import routes
from .demo import seed_demo
from .entities import ENTITIES, MIGRATIONS, REFERENCES


def _summary_kpi(value: str, count: str):
    def compute() -> dict:
        summary = services.invoice_summary()
        return {"value": summary[value], "count": summary[count]}
    return compute


def _orders_to_deliver() -> dict:
    row = db.fetch_one("SELECT COUNT(*) AS n FROM sales_orders WHERE status = 'confirmed'")
    return {"value": row["n"], "count": row["n"]}


MODULE = Module(
    key="sales", slug="ventes", label=("Ventes", "Sales"),
    description=("Clients, devis et factures (création en une phrase, envoi, relances), commandes clients.",
                 "Customers, quotes and invoices (written in one sentence, sent, chased), sales orders."),
    icon="ReceiptText", order=40, upgrade_enabled=True,
    migrations=MIGRATIONS, entities=ENTITIES,
    pages=[
        Page("factures", ("Factures et devis", "Invoices and quotes"), component="sales.invoices", icon="ReceiptText"),
        Page("commandes", ("Commandes clients", "Sales orders"), entity="sales.orders", icon="ShoppingBag"),
        Page("clients", ("Clients", "Customers"), entity="sales.clients", icon="Building2"),
    ],
    router=routes.router,
    jobs=("generate_pdf", "send_invoice", "auto_reminders"),
    kpis=[
        Kpi("to_collect", ("À encaisser", "To collect"), _summary_kpi("to_collect", "to_collect_count"), unit="money",
            foot=("{n} facture(s) en attente", "{n} pending invoice(s)"), icon="Wallet", path="/ventes/factures"),
        Kpi("overdue", ("Factures en retard", "Overdue invoices"), _summary_kpi("overdue_total", "overdue_count"), unit="money",
            foot=("{n} facture(s) échue(s)", "{n} overdue invoice(s)"), icon="AlertTriangle",
            path="/ventes/factures?status=overdue", alert=lambda d: (d.get("value") or 0) > 0),
        Kpi("paid_month", ("Encaissé ce mois", "Collected this month"), _summary_kpi("paid_month", "paid_month_count"),
            unit="money", foot=("{n} paiement(s)", "{n} payment(s)"), icon="ReceiptText", path="/ventes/factures"),
        Kpi("quotes_pending", ("Devis en attente", "Pending quotes"), _summary_kpi("quotes_pending", "quotes_pending_count"),
            unit="money", foot=("{n} devis", "{n} quote(s)"), icon="FileSignature", path="/ventes/factures?tab=quote"),
        Kpi("orders_to_deliver", ("Commandes à livrer", "Orders to deliver"), _orders_to_deliver, icon="Truck",
            path="/ventes/commandes?f_status=confirmed"),
    ],
    shortcuts=[
        Shortcut("new_invoice", ("Nouvelle facture", "New invoice"), "/ventes/factures?new=invoice", icon="Plus"),
        Shortcut("new_order", ("Nouvelle commande", "New order"), "/ventes/commandes?new=1", icon="ShoppingBag"),
    ],
    references=REFERENCES,
    seed_demo=seed_demo,
    reset_tables=("sales_order_lines", "sales_orders"),
)
