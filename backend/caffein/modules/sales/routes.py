# SPDX-License-Identifier: AGPL-3.0-or-later
"""Routes des Ventes : clients, factures et devis (écran sur mesure). Lecture pour GET, écriture sinon."""

from __future__ import annotations

import re
from typing import Any

from fastapi import Body, Depends, Query, Response

from ... import ai, services
from ...core.deps import current_user, module_router
from ...jobs import run_job
from ...utils import today

router = module_router("sales")


# ── Clients ──────────────────────────────────────────────────────────────
@router.get("/clients")
def clients() -> list[dict]:
    return services.list_clients()


@router.post("/clients", status_code=201)
def create_client(data: dict = Body(...)) -> dict:
    return services.create_client(data)


@router.put("/clients/{client_id}")
def update_client(client_id: int, data: dict = Body(...)) -> dict:
    return services.update_client(client_id, data)


@router.delete("/clients/{client_id}", status_code=204)
def delete_client(client_id: int) -> Response:
    services.delete_client(client_id)
    return Response(status_code=204)


# ── Factures & devis ─────────────────────────────────────────────────────
@router.get("/invoices")
def invoices(kind: str | None = Query(None, pattern="^(invoice|quote)$")) -> list[dict]:
    return services.list_invoices(kind)


@router.get("/invoices/summary")
def invoices_summary() -> dict:
    return services.invoice_summary()


@router.post("/invoices/preview")
def invoice_preview(data: dict = Body(...)) -> dict:
    """Totaux d'un document en cours de saisie : calculés par le serveur, affichés par l'interface."""
    return services.preview_totals(data)


@router.post("/invoices", status_code=201)
def create_invoice(data: dict = Body(...)) -> dict:
    return services.create_invoice(data)


@router.post("/invoices/assistant", status_code=201)
def invoice_assistant(payload: dict = Body(...)) -> dict:
    """Langage naturel → brouillon (« Mission logo pour Jean Martin, 800 €, livraison le 15 »)."""
    text = str(payload.get("text", "")).strip()
    if len(text) < 4:
        raise ValueError("Décrivez la prestation à facturer.")
    kind_hint = payload.get("kind") if payload.get("kind") in ("invoice", "quote") else None
    parsed = ai.parse_invoice_request(text, services.list_clients(), today(), kind_hint)
    profile = services.get_profile()

    client, created_client = None, False
    if parsed.get("existing_client_id"):
        client = services.get_client(int(parsed["existing_client_id"]))
    if client is None and parsed.get("client_name"):
        before = len(services.list_clients())
        client = services.find_or_create_client(parsed["client_name"], parsed.get("client_contact", ""), parsed.get("client_email"))
        created_client = len(services.list_clients()) > before

    items = parsed["items"]
    if parsed.get("amounts_include_vat") and not profile["vat_exempt"]:
        items = [{**it, "unit_price": round(float(it["unit_price"]) / (1 + profile["default_vat_rate"]), 2)} for it in items]
    data: dict[str, Any] = {
        "kind": parsed["kind"], "client_id": client["id"] if client else None, "title": parsed.get("title", ""),
        "items": items, "delivery_date": parsed.get("delivery_date"), "notes": parsed.get("notes", ""), "source_text": text,
    }
    if parsed.get("due_in_days"):
        data["due_date"] = ai.due_date_from(today(), parsed["due_in_days"], profile["payment_terms_days"]).isoformat()
    invoice = services.create_invoice(data)
    return {"invoice": invoice, "parsed_by": parsed.get("parsed_by"), "created_client": created_client}


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: int) -> dict:
    return services.get_invoice(invoice_id)


@router.put("/invoices/{invoice_id}")
def update_invoice(invoice_id: int, data: dict = Body(...)) -> dict:
    return services.update_invoice(invoice_id, data)


@router.delete("/invoices/{invoice_id}", status_code=204)
def delete_invoice(invoice_id: int) -> Response:
    services.delete_invoice(invoice_id)
    return Response(status_code=204)


@router.post("/invoices/{invoice_id}/finalize")
def finalize_invoice(invoice_id: int) -> dict:
    return services.finalize_invoice(invoice_id)


@router.post("/invoices/{invoice_id}/send")
def send_invoice(invoice_id: int, payload: dict = Body(default={}), user: dict = Depends(current_user)) -> dict:
    inv = services.get_invoice(invoice_id)
    recipient = (payload.get("recipient_email") or (inv["client"] or {}).get("email") or "").strip()
    if not recipient:
        # vérifié avant d'émettre : un brouillon ne doit pas recevoir de numéro si l'envoi est impossible
        raise ValueError("Ajoutez une adresse email au client avant l'envoi (onglet Clients).")
    if inv["status"] == "draft":
        services.finalize_invoice(invoice_id)
    run = run_job("send_invoice", trigger="manual", actor=user["email"], invoice_id=invoice_id,
                  recipient_email=payload.get("recipient_email"))
    return {"run": run, "invoice": services.get_invoice(invoice_id)}


@router.post("/invoices/{invoice_id}/paid")
def invoice_paid(invoice_id: int, payload: dict = Body(default={})) -> dict:
    return services.mark_paid(invoice_id, payload.get("paid_at"))


@router.post("/invoices/{invoice_id}/cancel")
def invoice_cancel(invoice_id: int) -> dict:
    return services.cancel_invoice(invoice_id)


@router.post("/invoices/{invoice_id}/remind")
def invoice_remind(invoice_id: int, user: dict = Depends(current_user)) -> dict:
    run = run_job("auto_reminders", trigger="manual", actor=user["email"], invoice_id=invoice_id, force=True)
    return {"run": run, "invoice": services.get_invoice(invoice_id)}


@router.post("/invoices/{invoice_id}/quote-status")
def quote_status(invoice_id: int, payload: dict = Body(...)) -> dict:
    return services.set_quote_status(invoice_id, str(payload.get("status")))


@router.post("/invoices/{invoice_id}/convert", status_code=201)
def quote_convert(invoice_id: int) -> dict:
    return services.convert_quote(invoice_id)


def pdf_response(content: bytes, filename: str, download: bool) -> Response:
    disposition = "attachment" if download else "inline"
    safe = re.sub(r"[^\w.-]", "_", filename)
    return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'{disposition}; filename="{safe}"'})


@router.get("/invoices/{invoice_id}/pdf")
def invoice_pdf(invoice_id: int, download: bool = False) -> Response:
    content, filename = services.render_pdf_bytes(invoice_id)
    return pdf_response(content, filename, download)
