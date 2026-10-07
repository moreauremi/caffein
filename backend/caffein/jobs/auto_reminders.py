# SPDX-License-Identifier: AGPL-3.0-or-later
"""Relances automatiques des factures impayées.

Remplace le workflow n8n « CAFFEIN - Relances automatiques » (cron 9h00 Paris) :
factures envoyées et échues → choix du ton → rédaction par Claude → email au
client → mise à jour du compteur de relances → notification au freelance.

Améliorations par rapport au workflow d'origine : une relance au plus tous les
7 jours par facture (au lieu de chaque jour) et 3 relances maximum.

    python -m caffein run auto_reminders
"""

from __future__ import annotations

from .. import ai, config, db, emailer, services
from ..email_templates import TONE_LABELS, reminder_email, reminder_notice_email, reminder_subject, sender_name
from ..utils import fmt_date_long, fmt_money, parse_date, today
from . import daily, job


def choose_tone(reminder_count: int, days_overdue: int) -> str:
    """gentle → firm → final (mise en demeure amiable)."""
    if reminder_count == 0:
        return "gentle" if days_overdue <= 7 else "firm"
    if reminder_count == 1 and days_overdue <= 21:
        return "firm"
    return "final"


def build_context(inv: dict, profile: dict) -> dict:
    client = inv["client"] or {}
    tone = choose_tone(inv["reminder_count"], inv["days_overdue"])
    return {
        "invoice_id": inv["id"], "invoice_number": inv["number"],
        "amount_formatted": fmt_money(inv["total"]), "due_date_formatted": fmt_date_long(inv["due_date"]),
        "days_overdue": inv["days_overdue"], "reminder_count": inv["reminder_count"],
        "new_reminder_count": inv["reminder_count"] + 1, "tone": tone, "tone_label": TONE_LABELS[tone],
        "sender_name": sender_name(profile), "client_name": client.get("contact_name") or client.get("name") or "",
        "recipient_email": client.get("email") or "", "portal_url": inv["portal_url"],
    }


def send_reminder(inv: dict, profile: dict) -> dict:
    ctx = build_context(inv, profile)
    body, written_by = ai.write_reminder(ctx)
    record = emailer.send_email(
        to=ctx["recipient_email"], subject=reminder_subject(ctx["tone"], inv["number"], inv["days_overdue"]),
        html=reminder_email(ctx, body), kind="reminder", from_name=ctx["sender_name"],
        reply_to=profile.get("email") or None, invoice_id=inv["id"],
        meta={"tone": ctx["tone"], "written_by": written_by, "days_overdue": inv["days_overdue"]},
        tags={"type": "reminder", "tone": ctx["tone"], "invoice_id": inv["id"]},
    )
    if record["status"] == "failed":
        return {"ok": False, "invoice": inv["number"], "error": record["error"], "tone": ctx["tone"]}

    db.update("invoices", inv["id"], {"reminder_count": ctx["new_reminder_count"], "last_reminder_at": db.now_iso(),
                                      "last_reminder_tone": ctx["tone"], "updated_at": db.now_iso()})
    if profile.get("email"):
        subject, html = reminder_notice_email(ctx)
        emailer.send_email(to=profile["email"], subject=subject, html=html, kind="notification",
                           invoice_id=inv["id"], meta={"about": "reminder"})
    return {"ok": True, "invoice": inv["number"], "client": ctx["client_name"], "tone": ctx["tone"],
            "written_by": written_by, "email_status": record["status"]}


@job(
    "auto_reminders",
    title="Relances d'impayés",
    description="Relance les factures échues avec un ton progressif (amical, ferme, mise en demeure), "
                "rédigé par l'IA, puis prévient le freelance.",
    replaces="CAFFEIN - Relances automatiques",
    schedule=daily("09:00"),
)
def run(invoice_id: int | None = None, force: bool = False) -> dict:
    ref = today()
    profile = services.get_profile()
    if invoice_id:
        candidates = [services.get_invoice(int(invoice_id))]
        if candidates[0]["display_status"] != "overdue":
            return {"status": "error", "summary": "Cette facture n'est pas en retard de paiement"}
    else:
        candidates = [services.get_invoice(i["id"]) for i in services.list_invoices("invoice") if i["display_status"] == "overdue"]

    if not candidates:
        return {"summary": "Aucune facture en retard", "quiet": True}

    results, skipped = [], []
    for inv in candidates:
        last = parse_date(inv.get("last_reminder_at"))
        if not force and inv["reminder_count"] >= config.REMINDER_MAX:
            skipped.append({"invoice": inv["number"], "reason": "3 relances déjà envoyées"})
            continue
        if not force and last and (ref - last).days < config.REMINDER_INTERVAL_DAYS:
            skipped.append({"invoice": inv["number"], "reason": f"Dernière relance il y a {(ref - last).days} j"})
            continue
        results.append(send_reminder(inv, profile))

    sent = [r for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]
    if not results:
        return {"summary": f"{len(skipped)} facture(s) en retard, aucune relance due aujourd'hui", "quiet": True, "skipped": skipped}
    summary = f"{len(sent)} relance{'s' if len(sent) > 1 else ''} envoyée{'s' if len(sent) > 1 else ''}"
    if failed:
        summary += f" · {len(failed)} en échec"
    return {"status": "success" if sent else "error", "summary": summary, "notable": True,
            "sent": sent, "failed": failed, "skipped": skipped}
