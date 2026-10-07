# SPDX-License-Identifier: AGPL-3.0-or-later
"""Alertes fiscales et résumé hebdomadaire (préférences « Notifications »).

Nouveau script : rend fonctionnels les réglages profiles.notif_tva / notif_echeance /
notif_hebdo décrits dans la doc (§10) :
- Alertes TVA : email quand la balance TVA du mois dépasse le seuil choisi ;
- Rappels d'échéances : 5 jours avant la date limite TVA ou URSSAF ;
- Résumé hebdomadaire : chaque lundi matin.

    python -m caffein run fiscal_alerts
"""

from __future__ import annotations

from datetime import timedelta

from .. import db, emailer, fiscal, services
from ..email_templates import deadline_email, tva_alert_email, weekly_summary_email
from ..utils import fmt_date, fmt_date_long, parse_date, today
from . import daily, job

DEADLINE_NOTICE_DAYS = 5


def _already_sent(key: str) -> bool:
    return db.fetch_one("SELECT 1 AS x FROM alerts_sent WHERE key = ?", (key,)) is not None


def _send_once(key: str, to: str, subject: str, html: str) -> bool:
    if _already_sent(key):
        return False
    record = emailer.send_email(to=to, subject=subject, html=html, kind="alert", meta={"alert": key})
    if record["status"] != "failed":
        db.execute("INSERT OR REPLACE INTO alerts_sent (key, sent_at) VALUES (?, ?)", (key, db.now_iso()))
        return True
    return False


def weekly_stats(ref) -> dict:
    start = ref - timedelta(days=7)
    docs = [d for d in services.list_documents(start, ref) if d["source"] != "invoice"]
    invoices = services.list_invoices("invoice")
    issued = [i for i in invoices if i["status"] != "draft" and (parse_date(i["issued_at"]) or start) > start]
    paid = [i for i in invoices if i["status"] == "paid" and (parse_date(i["paid_at"]) or start) > start]
    summary = services.invoice_summary()
    return {"documents": len(docs), "invoices": len(issued), "paid": sum(i["total"] for i in paid),
            "pending": summary["to_collect"], "overdue_count": summary["overdue_count"], "overdue_total": summary["overdue_total"]}


@job(
    "fiscal_alerts",
    title="Alertes TVA & échéances",
    description="Prévient par email quand la TVA à reverser dépasse votre seuil, 5 jours avant chaque échéance "
                "TVA/URSSAF, et envoie le résumé du lundi.",
    replaces="Nouveau (réglages Notifications)",
    schedule=daily("08:00"),
)
def run() -> dict:
    ref = today()
    profile = services.get_profile()
    if not profile.get("email"):
        return {"status": "warning", "summary": "Aucune adresse email sur le profil"}
    sent = []

    if profile["notif_echeance"]:
        for item in services.upcoming_deadlines(ref):
            if 0 <= item["days_left"] <= DEADLINE_NOTICE_DAYS:
                subject, html = deadline_email(item["label"], fmt_date_long(item["date"]), item.get("amount"), item["path"])
                if _send_once(f"deadline:{item['type']}:{item['date']}", profile["email"], subject, html):
                    sent.append(f"rappel {item['label']} ({fmt_date(item['date'])})")

    if profile["notif_tva"] and not profile["vat_exempt"]:
        month = fiscal.tva_period("month", ref)
        balance = services.tva_dashboard("month")["metrics"]["balance"]
        if balance > profile["tva_alert_threshold"]:
            subject, html = tva_alert_email(balance, profile["tva_alert_threshold"], month.label,
                                            fmt_date_long(fiscal.tva_deadline(month.end)))
            if _send_once(f"tva:{ref:%Y-%m}", profile["email"], subject, html):
                sent.append("alerte TVA")

    if profile["notif_hebdo"] and ref.weekday() == 0:
        subject, html = weekly_summary_email(weekly_stats(ref))
        if _send_once(f"weekly:{ref.isocalendar().year}-W{ref.isocalendar().week:02d}", profile["email"], subject, html):
            sent.append("résumé hebdomadaire")

    if not sent:
        return {"summary": "Aucune alerte à envoyer aujourd'hui", "quiet": True}
    return {"summary": "Envoyé : " + ", ".join(sent), "notable": True, "sent": sent}
