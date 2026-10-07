# SPDX-License-Identifier: AGPL-3.0-or-later
"""Séquence d'emails d'onboarding (J0, J+1, J+3, J+7).

Remplace le workflow n8n « CAFFEIN - Onboarding » (webhook user.created → email de
bienvenue → attente J+1 → facture créée ? → conseil ou félicitations → J+3 → J+7).
Les « Wait » n8n sont remplacés par un état en base (profile.onboarding_step) vérifié
chaque jour : un email au plus par exécution.

    python -m caffein run onboarding_emails
"""

from __future__ import annotations

from .. import db, emailer, services
from ..email_templates import onboarding_email
from ..utils import parse_date, today
from . import daily, job

# étape courante → (jours depuis l'inscription, email si aucune facture)
SEQUENCE = {1: (1, "tip"), 2: (3, "einvoicing"), 3: (7, "help")}


@job(
    "onboarding_emails",
    title="Emails d'onboarding",
    description="Bienvenue à l'installation, puis conseils à J+1, J+3 et J+7 tant qu'aucune facture n'est émise "
                "(félicitations dès la première).",
    replaces="CAFFEIN - Onboarding",
    schedule=daily("10:00"),
)
def run() -> dict:
    profile = services.get_profile()
    if not profile["notif_onboarding"]:
        return {"summary": "Emails de prise en main désactivés", "quiet": True}
    if profile["onboarding_done"]:
        return {"summary": "Séquence d'onboarding terminée", "quiet": True}
    if not profile.get("email"):
        return {"status": "warning", "summary": "Aucune adresse email sur le profil"}

    step = profile["onboarding_step"]
    days = (today() - (parse_date(profile["created_at"]) or today())).days
    has_invoice = db.fetch_one("SELECT COUNT(*) AS n FROM invoices WHERE kind = 'invoice' AND status != 'draft'")["n"] > 0
    name = profile.get("full_name") or ""

    if step == 0:
        email_key, next_step, done = "welcome", 1, False
    elif step in SEQUENCE and days >= SEQUENCE[step][0]:
        if has_invoice:
            email_key, next_step, done = "congrats", step, True
        else:
            email_key, next_step, done = SEQUENCE[step][1], step + 1, step == 3
    else:
        return {"summary": f"Prochain email d'onboarding à J+{SEQUENCE.get(step, (0,))[0]}", "quiet": True}

    subject, html = onboarding_email(email_key, name)
    record = emailer.send_email(to=profile["email"], subject=subject, html=html, kind="onboarding",
                                from_name="CAFFEIN", meta={"step": email_key})
    if record["status"] == "failed":
        return {"status": "error", "summary": f"Échec de l'email « {subject} » : {record['error']}"}
    db.update("profile", 1, {"onboarding_step": next_step, "onboarding_done": int(done)})
    return {"summary": f"Email d'onboarding envoyé : « {subject} »", "notable": True, "step": email_key}
