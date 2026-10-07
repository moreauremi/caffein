# SPDX-License-Identifier: AGPL-3.0-or-later
"""Envoi d'une facture ou d'un devis par email, PDF en pièce jointe.

Remplace le workflow n8n « CAFFEIN - Envoi email facture » : vérification que le
PDF est prêt (3 tentatives maximum), gabarit HTML, envoi Resend, callback
email-sent / email-bounced (ici : mise à jour directe de la facture).

    python -m caffein run send_invoice --invoice-id 12
"""

from __future__ import annotations

from pathlib import Path

from .. import db, emailer, services
from ..email_templates import invoice_email, sender_name
from . import job, on_event
from .generate_pdf import run as generate_pdf

MAX_ATTEMPTS = 3


@job(
    "send_invoice",
    title="Envoi des factures",
    description="Émet le document si besoin, vérifie que le PDF est prêt puis l'envoie au client avec un lien de consultation.",
    replaces="CAFFEIN - Envoi email facture",
    schedule=on_event("Au clic sur « Envoyer »"),
    manual=False,
)
def run(invoice_id: int, recipient_email: str | None = None) -> dict:
    inv = services.get_invoice(int(invoice_id))
    if inv["status"] == "draft":
        inv = services.finalize_invoice(inv["id"])

    attempts = 0
    while not inv["has_pdf"] and attempts < MAX_ATTEMPTS:
        attempts += 1
        generate_pdf(invoice_id=inv["id"])
        inv = services.get_invoice(inv["id"])
    if not inv["has_pdf"]:
        return {"status": "error", "summary": f"PDF indisponible après {MAX_ATTEMPTS} tentatives", "invoice_id": inv["id"]}

    recipient = (recipient_email or (inv["client"] or {}).get("email") or "").strip()
    if not recipient:
        return {"status": "error", "summary": "Le client n'a pas d'adresse email", "invoice_id": inv["id"]}

    profile = services.get_profile()
    subject, html = invoice_email(inv, inv["client"], profile, inv["portal_url"])
    pdf_path = Path(inv["pdf_path"])
    record = emailer.send_email(
        to=recipient, subject=subject, html=html, kind="quote" if inv["kind"] == "quote" else "invoice",
        from_name=sender_name(profile), reply_to=profile.get("email") or None,
        attachment=(pdf_path.name, pdf_path.read_bytes()), invoice_id=inv["id"],
        tags={"type": inv["kind"], "invoice_id": inv["id"]},
    )
    if record["status"] == "failed":
        return {"status": "error", "summary": f"Échec d'envoi à {recipient} : {record['error']}", "email_id": record["id"]}

    db.update("invoices", inv["id"], {"emailed_at": db.now_iso(), "emailed_to": recipient, "updated_at": db.now_iso()})
    label = "Devis" if inv["kind"] == "quote" else "Facture"
    mode = " (simulé)" if record["status"] == "simulated" else ""
    return {"summary": f"{label} {inv['number']} envoyé{'e' if label == 'Facture' else ''} à {recipient}{mode}",
            "notable": True, "invoice_id": inv["id"], "email_id": record["id"], "email_status": record["status"]}
