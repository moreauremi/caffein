# SPDX-License-Identifier: AGPL-3.0-or-later
"""Génération du PDF d'une facture ou d'un devis.

Remplace le workflow n8n « CAFFEIN - Génération PDF » (webhook invoice.created →
Fetch Invoice + Client + User → HTML → Gotenberg → Supabase Storage → callback).
Le PDF est rendu par ReportLab et archivé dans « Factures envoyées/<CLIENT>/ ».

    python -m caffein run generate_pdf --invoice-id 12
"""

from __future__ import annotations

from .. import db, services
from ..pdf_invoice import render_invoice_pdf
from . import job, on_event


@job(
    "generate_pdf",
    title="Génération des PDF",
    description="Crée le PDF A4 conforme (mentions légales, pénalités, TVA) à l'émission d'une facture ou d'un devis "
                "et l'archive dans « Factures envoyées ».",
    replaces="CAFFEIN - Génération PDF",
    schedule=on_event("À l'émission d'une facture ou d'un devis"),
    manual=False,
)
def run(invoice_id: int) -> dict:
    inv = services.get_invoice(int(invoice_id))
    if inv["status"] == "draft":
        return {"status": "error", "summary": "Impossible de générer le PDF définitif d'un brouillon"}

    pdf = render_invoice_pdf(inv, inv["client"], services.get_profile())
    target = services.invoice_pdf_target(inv)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(pdf)
    db.update("invoices", inv["id"], {"pdf_path": str(target), "updated_at": db.now_iso()})

    label = "Devis" if inv["kind"] == "quote" else "Facture"
    return {"summary": f"{label} {inv['number']} émis{'e' if label == 'Facture' else ''} — PDF archivé",
            "notable": True, "invoice_id": inv["id"], "file": target.name, "size": len(pdf)}
