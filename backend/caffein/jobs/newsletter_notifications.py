# SPDX-License-Identifier: AGPL-3.0-or-later
"""Newsletter → actualités de l'accueil.

Remplace le workflow n8n « Caffein - Notifications from newsletter » (Gmail Trigger
→ agent IA → insertion dans notification_caffein → suppression des plus anciennes
au-delà de 4). La boîte mail est lue en IMAP si CAFFEIN_IMAP_* est configuré ;
sinon le texte d'une newsletter peut être collé dans l'interface.

    python -m caffein run newsletter_notifications
    python -m caffein run newsletter_notifications --text "Objet : … "
"""

from __future__ import annotations

import email
import imaplib
import logging
import re
from email.header import decode_header, make_header
from html import unescape

from .. import ai, config, db
from . import every, job

log = logging.getLogger("caffein.jobs.newsletter")


def _message_text(msg: email.message.Message) -> str:
    subject = str(make_header(decode_header(msg.get("Subject", ""))))
    plain, html = "", ""
    for part in msg.walk() if msg.is_multipart() else [msg]:
        ctype = part.get_content_type()
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        text = payload.decode(part.get_content_charset() or "utf-8", "ignore")
        if ctype == "text/plain" and not plain:
            plain = text
        elif ctype == "text/html" and not html:
            html = unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(style|script).*?</\1>", "", text)))
    return f"Subject: {subject}\n\n{plain or html}"


def fetch_imap() -> list[str]:
    if not (config.IMAP_HOST and config.IMAP_USER and config.IMAP_PASSWORD):
        return []
    texts = []
    with imaplib.IMAP4_SSL(config.IMAP_HOST) as imap:
        imap.login(config.IMAP_USER, config.IMAP_PASSWORD)
        imap.select("INBOX")
        criteria = ["UNSEEN", "SUBJECT", '"newsletter"']
        if config.NEWSLETTER_SENDER:
            criteria += ["FROM", f'"{config.NEWSLETTER_SENDER}"']
        _, data = imap.search(None, *criteria)
        for num in (data[0] or b"").split():
            _, msg_data = imap.fetch(num, "(RFC822)")  # marque le message comme lu
            texts.append(_message_text(email.message_from_bytes(msg_data[0][1])))
    return texts


def add_notification(text: str) -> dict:
    data = ai.newsletter_to_notification(text)
    data["id"] = db.insert("notifications", {k: data[k] for k in ("title", "description", "tag", "color", "tag_color")}
                           | {"created_at": db.now_iso()})
    # On ne garde que les N plus récentes (ex-« Code in JavaScript1 » + « Delete a row »)
    db.execute("""DELETE FROM notifications WHERE id NOT IN (
                    SELECT id FROM notifications ORDER BY created_at DESC, id DESC LIMIT ?)""", (config.NOTIFICATIONS_KEPT,))
    return data


@job(
    "newsletter_notifications",
    title="Actualités depuis la newsletter",
    description="Lit les newsletters Caffein reçues, les résume avec l'IA en actualité taguée et ne garde que les 4 plus récentes.",
    replaces="Caffein - Notifications from newsletter",
    schedule=every(minutes=5),
)
def run(text: str | None = None) -> dict:
    try:
        texts = [text] if text else fetch_imap()
    except (imaplib.IMAP4.error, OSError) as exc:
        return {"status": "error", "summary": f"Connexion IMAP impossible : {exc}"}
    if not texts:
        reason = "Aucune nouvelle newsletter" if config.IMAP_HOST else "IMAP non configuré — collez une newsletter dans l'interface"
        return {"summary": reason, "quiet": True}

    created = [add_notification(t) for t in texts if t.strip()]
    titles = ", ".join(f"« {c['title']} »" for c in created[:3])
    return {"summary": f"{len(created)} actualité{'s' if len(created) > 1 else ''} publiée{'s' if len(created) > 1 else ''} : {titles}",
            "notable": True, "notifications": created}
