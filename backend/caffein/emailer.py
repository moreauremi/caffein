# SPDX-License-Identifier: AGPL-3.0-or-later
"""Envoi d'emails par SMTP ou par l'API Resend, ou simulation locale sans configuration.

Chaque email (réel ou simulé) est journalisé dans la table `emails` et une copie
HTML est écrite dans data/outbox/ — c'est la « boîte d'envoi » de l'interface.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import smtplib
import ssl
import urllib.error
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from . import config, db

log = logging.getLogger("caffein.email")


def mode() -> str:
    if config.SMTP_HOST:
        return "smtp"
    if config.RESEND_API_KEY:
        return "resend"
    return "simulation"


def status() -> dict:
    current = mode()
    provider = {"smtp": f"SMTP {config.SMTP_HOST}", "resend": "Resend"}.get(current)
    return {"provider": provider, "mode": current, "from": config.EMAIL_FROM_ADDRESS}


def _html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<(style|script).*?</\1>", "", html)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</tr>|</h\d>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _send_smtp(from_name: str, to: str, subject: str, html: str, reply_to: str | None,
               attachment: tuple[str, bytes] | None) -> str:
    msg = EmailMessage()
    msg["From"] = formataddr((from_name, config.EMAIL_FROM_ADDRESS))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=config.EMAIL_FROM_ADDRESS.split("@")[-1] or None)
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(_html_to_text(html))
    msg.add_alternative(html, subtype="html")
    if attachment:
        msg.add_attachment(attachment[1], maintype="application", subtype="pdf", filename=attachment[0])

    context = ssl.create_default_context()
    if config.SMTP_SECURITY == "ssl":
        server = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=20, context=context)
    else:
        server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20)
    with server:
        if config.SMTP_SECURITY == "starttls":
            server.starttls(context=context)
        if config.SMTP_USER:
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
        server.send_message(msg)
    return msg["Message-ID"]


def _sanitize_header(value: str) -> str:
    return re.sub(r"[\r\n<>\"]", " ", value or "").strip()


def send_email(
    *,
    to: str,
    subject: str,
    html: str,
    kind: str,
    from_name: str | None = None,
    reply_to: str | None = None,
    attachment: tuple[str, bytes] | None = None,
    invoice_id: int | None = None,
    meta: dict | None = None,
    tags: dict | None = None,
) -> dict:
    from_name = _sanitize_header(from_name or config.EMAIL_FROM_NAME)
    sender = f"{from_name} <{config.EMAIL_FROM_ADDRESS}>"
    record = {
        "kind": kind, "to_email": to, "from_email": sender, "subject": subject, "html": html,
        "attachment_name": attachment[0] if attachment else None, "status": "simulated",
        "provider_id": None, "error": None, "invoice_id": invoice_id,
        "meta": db.dumps(meta or {}), "created_at": db.now_iso(),
    }

    if not to or "@" not in to:
        record.update(status="failed", error="Adresse email du destinataire manquante")
    elif mode() == "smtp":
        try:
            record.update(status="sent", provider_id=_send_smtp(from_name, to, subject, html, reply_to, attachment))
        except (smtplib.SMTPException, OSError, ValueError) as exc:  # ValueError : en-tête invalide
            record.update(status="failed", error=f"SMTP : {exc}")
    elif mode() == "resend":
        payload = {"from": sender, "to": [to], "subject": subject, "html": html}
        if reply_to:
            payload["reply_to"] = reply_to
        if attachment:
            payload["attachments"] = [{"filename": attachment[0], "content": base64.b64encode(attachment[1]).decode("ascii")}]
        if tags:
            payload["tags"] = [{"name": k, "value": re.sub(r"[^\w-]", "_", str(v))} for k, v in tags.items()]
        request = urllib.request.Request(
            "https://api.resend.com/emails",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {config.RESEND_API_KEY}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as resp:
                body = json.loads(resp.read() or b"{}")
            record.update(status="sent", provider_id=body.get("id"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "ignore")[:300]
            record.update(status="failed", error=f"Resend HTTP {exc.code} : {detail}")
        except (urllib.error.URLError, TimeoutError) as exc:
            record.update(status="failed", error=f"Resend injoignable : {exc}")

    record["id"] = db.insert("emails", record)
    _write_outbox_copy(record)
    if record["status"] == "failed":
        log.warning("Email %s → %s en échec : %s", kind, to, record["error"])
    return record


def _write_outbox_copy(record: dict) -> None:
    config.OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}-{record['id']:05d}-{record['kind']}.html"
    (config.OUTBOX_DIR / name).write_text(record["html"], encoding="utf-8")
