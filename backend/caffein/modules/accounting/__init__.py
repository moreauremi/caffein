# SPDX-License-Identifier: AGPL-3.0-or-later
"""Comptabilité : TVA, URSSAF, justificatifs classés par l'IA (écrans historiques de Caffein)."""

from __future__ import annotations

from ... import db, fiscal, services
from ...core.modules import Kpi, Module, Page, Shortcut
from ...utils import cents, today
from . import routes


def _vat_balance() -> dict:
    period = fiscal.tva_period("month", today())
    collected = deductible = 0.0
    for doc in services.list_documents(period.start, period.end):
        if doc["tva_type"] == "collected":
            collected += doc["tva"] or 0
        else:
            deductible += doc["tva"] or 0
    return {"value": cents(collected - deductible)}


def _documents() -> dict:
    n = db.fetch_one("SELECT COUNT(*) AS n FROM documents WHERE source != 'invoice'")["n"]
    return {"value": n, "count": n}


MODULE = Module(
    key="accounting", slug="comptabilite", label=("Comptabilité", "Accounting"),
    description=("TVA, déclarations URSSAF et justificatifs lus et classés automatiquement.",
                 "VAT, social security returns and receipts read and filed automatically."),
    icon="Landmark", order=90, upgrade_enabled=True,
    pages=[
        Page("tva", ("TVA", "VAT"), component="accounting.vat", icon="Percent"),
        Page("urssaf", ("URSSAF", "Social security"), component="accounting.urssaf", icon="Landmark"),
        Page("justificatifs", ("Justificatifs", "Receipts"), component="accounting.documents", icon="FileStack"),
    ],
    router=routes.router,
    jobs=("process_inbox", "fiscal_alerts", "setup_drive"),
    kpis=[
        Kpi("vat_balance", ("Solde de TVA du mois", "VAT balance this month"), _vat_balance, unit="money",
            foot=("collectée moins déductible", "collected minus deductible"), icon="Percent", path="/comptabilite/tva"),
        Kpi("documents", ("Justificatifs classés", "Filed receipts"), _documents, icon="FileStack",
            foot=("lus et classés automatiquement", "read and filed automatically"), path="/comptabilite/justificatifs"),
    ],
    shortcuts=[
        Shortcut("upload", ("Déposer un justificatif", "Upload a receipt"), "/comptabilite/justificatifs", icon="Upload"),
    ],
)
