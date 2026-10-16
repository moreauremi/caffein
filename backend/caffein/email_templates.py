# SPDX-License-Identifier: AGPL-3.0-or-later
"""Gabarits HTML des emails, repris des workflows n8n (envoi de facture,
relances, séquence d'onboarding) et complétés par les alertes fiscales."""

from __future__ import annotations

from html import escape

from . import config
from .utils import fmt_date_long, fmt_money

TONE_COLORS = {"gentle": "#4f46e5", "firm": "#f59e0b", "final": "#dc2626"}
TONE_LABELS = {"gentle": "Relance amicale", "firm": "Relance ferme", "final": "Mise en demeure amiable"}
BRAND = "#C96610"


def _e(value: object) -> str:
    return escape(str(value or ""))


def sender_name(profile: dict) -> str:
    return profile.get("company") or profile.get("full_name") or "Caffein"


def client_name(client: dict | None) -> str:
    if not client:
        return ""
    return client.get("contact_name") or client.get("name") or ""


# ── Envoi de facture / devis (workflow 02-send-email) ────────────────────
def invoice_email(invoice: dict, client: dict | None, profile: dict, portal_url: str) -> tuple[str, str]:
    is_quote = invoice.get("kind") == "quote"
    doc_label = "devis" if is_quote else "facture"
    number = _e(invoice.get("number"))
    amount = fmt_money(invoice.get("total"))
    due = fmt_date_long(invoice.get("due_date"))
    sender = _e(sender_name(profile))
    greeting = _e(client_name(client)) or "Madame, Monsieur"

    if is_quote:
        intro = (f"Veuillez trouver ci-joint notre devis <strong>n° {number}</strong> d'un montant de "
                 f"<strong>{amount}</strong>{f', valable jusqu’au <strong>{due}</strong>' if due else ''}.")
        cta = "Consulter le devis"
    else:
        intro = (f"Veuillez trouver ci-joint votre facture <strong>n° {number}</strong> d'un montant de "
                 f"<strong>{amount}</strong>{f', payable avant le <strong>{due}</strong>' if due else ''}.")
        cta = "Voir la facture &amp; régler"

    due_row = f"""<tr><td colspan="2" style="padding:12px 20px;">
      <span style="font-size:12px;color:#9ca3af;text-transform:uppercase;font-weight:600;">{'Validité' if is_quote else 'Échéance'}</span><br/>
      <span style="font-size:14px;color:#374151;">{due}</span></td></tr>""" if due else ""

    footer_address = " — ".join(x for x in [_e(profile.get("address")), f"{_e(profile.get('zip_code'))} {_e(profile.get('city'))}".strip()] if x)
    html = f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f4f4f5;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f4f5;padding:32px 0;"><tr><td align="center">
  <table role="presentation" width="580" cellspacing="0" cellpadding="0" style="background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08);">
    <tr><td style="background:#4f46e5;padding:28px 32px;"><span style="font-size:22px;font-weight:700;color:#ffffff;letter-spacing:-0.3px;">{sender}</span></td></tr>
    <tr><td style="padding:32px;">
      <p style="margin:0 0 16px;font-size:15px;color:#374151;line-height:1.6;">Bonjour {greeting},</p>
      <p style="margin:0 0 24px;font-size:15px;color:#374151;line-height:1.6;">{intro}</p>
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;margin-bottom:28px;">
        <tr>
          <td style="padding:16px 20px;border-bottom:1px solid #e5e7eb;"><span style="font-size:12px;color:#9ca3af;text-transform:uppercase;font-weight:600;">{doc_label.capitalize()}</span><br/>
            <span style="font-size:15px;color:#111827;font-weight:600;">{number}</span></td>
          <td style="padding:16px 20px;border-bottom:1px solid #e5e7eb;text-align:right;"><span style="font-size:12px;color:#9ca3af;text-transform:uppercase;font-weight:600;">Montant</span><br/>
            <span style="font-size:15px;color:#111827;font-weight:600;">{amount}</span></td>
        </tr>{due_row}
      </table>
      <table role="presentation" cellspacing="0" cellpadding="0" style="margin:0 auto 28px;"><tr><td style="background:#4f46e5;border-radius:6px;">
        <a href="{_e(portal_url)}" target="_blank" style="display:inline-block;padding:14px 32px;font-size:15px;font-weight:600;color:#ffffff;text-decoration:none;">{cta}</a>
      </td></tr></table>
      <p style="margin:0;font-size:13px;color:#9ca3af;line-height:1.5;text-align:center;">Le {doc_label} est également joint à cet email au format PDF.</p>
    </td></tr>
    <tr><td style="padding:20px 32px;border-top:1px solid #e5e7eb;background:#fafafa;">
      <p style="margin:0;font-size:12px;color:#9ca3af;line-height:1.5;">{sender}{f' — {footer_address}' if footer_address else ''}<br/>{_e(profile.get('email'))} {f'· {_e(profile.get("phone"))}' if profile.get('phone') else ''}</p>
    </td></tr>
  </table>
  <p style="margin:24px 0 0;font-size:11px;color:#b0b0b0;text-align:center;">Cet email a été envoyé automatiquement via Caffein.</p>
</td></tr></table>
</body></html>"""
    subject = f"{'Devis' if is_quote else 'Facture'} {invoice.get('number')} — {sender_name(profile)}"
    return subject, html


# ── Relance (workflow 03-auto-reminders) ─────────────────────────────────
def reminder_subject(tone: str, number: str, days_overdue: int) -> str:
    return {
        "gentle": f"Rappel : facture {number} en attente",
        "firm": f"Relance : facture {number} — {days_overdue} jours de retard",
        "final": f"Mise en demeure amiable : facture {number}",
    }.get(tone, f"Relance facture {number}")


def reminder_email(ctx: dict, body_html: str) -> str:
    color = TONE_COLORS.get(ctx["tone"], "#4f46e5")
    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f4f4f5;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f4f5;padding:32px 0;"><tr><td align="center">
  <table role="presentation" width="580" cellspacing="0" cellpadding="0" style="background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.08);">
    <tr><td style="background:{color};padding:24px 32px;">
      <span style="font-size:20px;font-weight:700;color:#ffffff;">{_e(ctx['sender_name'])}</span>
      <span style="display:block;font-size:12px;color:rgba(255,255,255,0.85);margin-top:4px;">{_e(ctx['tone_label'])} — Facture n° {_e(ctx['invoice_number'])}</span>
    </td></tr>
    <tr><td style="padding:32px;font-size:15px;color:#374151;line-height:1.7;">{body_html}</td></tr>
    <tr><td style="padding:0 32px 32px;" align="center">
      <a href="{_e(ctx['portal_url'])}" target="_blank" style="display:inline-block;padding:14px 36px;background:{color};color:#ffffff;font-size:15px;font-weight:600;text-decoration:none;border-radius:6px;">Régler la facture</a>
    </td></tr>
    <tr><td style="padding:0 32px 24px;">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;">
        <tr><td style="padding:14px 20px;font-size:13px;"><strong>Facture :</strong> {_e(ctx['invoice_number'])}</td>
            <td style="padding:14px 20px;font-size:13px;text-align:right;"><strong>Montant :</strong> {_e(ctx['amount_formatted'])}</td></tr>
        <tr><td style="padding:0 20px 14px;font-size:13px;"><strong>Échéance :</strong> {_e(ctx['due_date_formatted'])}</td>
            <td style="padding:0 20px 14px;font-size:13px;text-align:right;color:#dc2626;"><strong>Retard :</strong> {ctx['days_overdue']} jours</td></tr>
      </table>
    </td></tr>
    <tr><td style="padding:16px 32px;border-top:1px solid #e5e7eb;background:#fafafa;">
      <p style="margin:0;font-size:11px;color:#9ca3af;">Cet email de relance a été envoyé automatiquement pour le compte de {_e(ctx['sender_name'])} via Caffein.</p>
    </td></tr>
  </table>
</td></tr></table>
</body></html>"""


def reminder_notice_email(ctx: dict) -> tuple[str, str]:
    """Notification au freelance : « Relance automatique envoyée »."""
    subject = f"Relance envoyée : facture {ctx['invoice_number']} — {ctx['client_name']}"
    html = f"""<div style="font-family:Helvetica,Arial,sans-serif;max-width:560px;margin:0 auto;padding:24px;">
<h2 style="color:#111827;font-size:18px;margin:0 0 16px;">Relance automatique envoyée</h2>
<p style="color:#374151;font-size:14px;line-height:1.6;margin:0 0 16px;">Une relance <strong>{_e(ctx['tone_label'].lower())}</strong> a été envoyée à
<strong>{_e(ctx['client_name'])}</strong> pour la facture n° <strong>{_e(ctx['invoice_number'])}</strong>.</p>
<table style="width:100%;background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;border-collapse:collapse;margin-bottom:16px;">
<tr><td style="padding:12px 16px;font-size:13px;"><strong>Montant :</strong> {_e(ctx['amount_formatted'])}</td>
<td style="padding:12px 16px;font-size:13px;text-align:right;"><strong>Retard :</strong> {ctx['days_overdue']} jours</td></tr>
<tr><td style="padding:0 16px 12px;font-size:13px;"><strong>Relance n° :</strong> {ctx['new_reminder_count']}</td>
<td style="padding:0 16px 12px;font-size:13px;text-align:right;"><strong>Ton :</strong> {_e(ctx['tone_label'])}</td></tr></table>
<p style="color:#9ca3af;font-size:12px;margin:0;">Vous n'avez rien à faire : Caffein continue le suivi automatiquement.</p></div>"""
    return subject, html


# ── Emails Caffein → freelance (onboarding, alertes) ─────────────────────
def _brand_email(title: str, paragraphs: list[str], cta_label: str, cta_path: str, highlight: str = "") -> str:
    body = "".join(f"<p style='font-size:16px;color:#5C574F;line-height:1.6;margin:0 0 20px;'>{p}</p>" for p in paragraphs)
    box = (f"<div style='background:#FFF8F0;border:1px solid #FDDAAB;border-radius:12px;padding:20px;margin-bottom:24px;"
           f"font-size:16px;color:#873D14;'>{highlight}</div>") if highlight else ""
    return f"""<div style="font-family:system-ui,-apple-system,sans-serif;max-width:560px;margin:0 auto;padding:40px 20px;">
<div style="text-align:center;margin-bottom:32px;"><div style="display:inline-block;background:{BRAND};color:white;font-size:18px;font-weight:700;padding:10px 16px;border-radius:12px;letter-spacing:1px;">CAFFEIN</div></div>
<h1 style="font-size:24px;color:#1E1C19;margin:0 0 16px;">{title}</h1>{body}{box}
<div style="text-align:center;margin:12px 0 32px;"><a href="{_e(config.APP_URL + cta_path)}" style="display:inline-block;background:{BRAND};color:white;text-decoration:none;padding:14px 28px;border-radius:12px;font-size:16px;font-weight:600;">{cta_label}</a></div>
<p style="font-size:13px;color:#908A7E;text-align:center;">Caffein — logiciel libre de gestion pour freelances et TPE</p></div>"""


def onboarding_email(step: str, name: str) -> tuple[str, str]:
    """Emails de prise en main envoyés à l'utilisateur principal de l'instance."""
    n = _e(name.split(" ")[0] if name else "")
    if step == "welcome":
        return "Bienvenue dans Caffein", _brand_email(
            f"Bienvenue {n} !",
            ["Votre instance Caffein est prête. Elle tourne en arrière-plan : classement des justificatifs, "
             "relances des impayés, suivi de la TVA et des déclarations URSSAF.",
             "Pour commencer, décrivez simplement ce que vous voulez facturer : Caffein s'occupe de la numérotation, "
             "du PDF avec les mentions légales et de l'envoi."],
            "Créer ma première facture", "/ventes/factures")
    if step == "tip":
        return "Une phrase suffit pour créer une facture", _brand_email(
            "C'est aussi simple que ça",
            ["Dans « Factures & devis », écrivez par exemple :"],
            "Essayer maintenant", "/ventes/factures",
            highlight="<em>« Mission logo pour Jean Martin, 800 €, livraison le 15 »</em>")
    if step == "einvoicing":
        return "La facturation électronique, c'est maintenant", _brand_email(
            "Le saviez-vous ?",
            ["Depuis le 1er septembre 2026, toutes les entreprises doivent pouvoir recevoir des factures électroniques. "
             "L'émission deviendra obligatoire pour les micro-entrepreneurs à partir du 1er septembre 2027.",
             "<strong style='color:#1E1C19;'>Prenez de l'avance :</strong> vos factures Caffein sont numérotées, "
             "archivées et contiennent déjà les nouvelles mentions (SIREN du client, nature de l'opération)."],
            "Créer ma première facture", "/ventes/factures")
    if step == "help":
        return "Besoin d'aide pour démarrer ?", _brand_email(
            "Un coup de main ?",
            ["Aucune facture n'a encore été émise sur votre instance. Pas de souci : changer ses habitudes prend du temps.",
             "La documentation (README du projet) explique la configuration des emails, de l'IA et des sauvegardes. "
             "Une question ou un bug ? Ouvrez une discussion ou un ticket sur le dépôt du projet."],
            "Ouvrir Caffein", "/")
    return "Votre première facture est partie ! 🎉", _brand_email(
        "Bravo, c'est fait !",
        ["Votre première facture a été émise avec Caffein. Les relances partiront toutes seules si le client tarde à payer.",
         "Caffein est un logiciel libre : si l'outil vous rend service, une étoile ou une contribution sur le dépôt "
         "aide le projet à vivre."],
        "Continuer sur Caffein", "/")


def tva_alert_email(balance: float, threshold: float, period_label: str, deadline: str) -> tuple[str, str]:
    return f"Alerte TVA : {fmt_money(balance)} à reverser", _brand_email(
        "Ta balance de TVA dépasse ton seuil",
        [f"Sur la période <strong>{_e(period_label)}</strong>, ta TVA à reverser atteint <strong>{fmt_money(balance)}</strong> "
         f"(seuil d'alerte : {fmt_money(threshold)}).",
         f"Pense à mettre cette somme de côté : elle sera à payer avant le <strong>{_e(deadline)}</strong>."],
        "Voir le suivi TVA", "/comptabilite/tva")


def deadline_email(label: str, deadline: str, amount: float | None, path: str) -> tuple[str, str]:
    amount_txt = f" Montant estimé : <strong>{fmt_money(amount)}</strong>." if amount is not None else ""
    return f"Rappel d'échéance : {label} avant le {deadline}", _brand_email(
        "Une échéance approche",
        [f"<strong>{_e(label)}</strong> est à effectuer avant le <strong>{_e(deadline)}</strong>.{amount_txt}",
         "Toutes les données sont déjà calculées à partir de tes factures : il ne te reste qu'à reporter le montant."],
        "Ouvrir le tableau de bord", path)


def weekly_summary_email(stats: dict) -> tuple[str, str]:
    lines = [
        f"<strong>{stats['documents']}</strong> document(s) classé(s) et <strong>{stats['invoices']}</strong> facture(s) émise(s) cette semaine.",
        f"Encaissé cette semaine : <strong>{fmt_money(stats['paid'])}</strong> — reste à encaisser : <strong>{fmt_money(stats['pending'])}</strong>.",
    ]
    if stats["overdue_count"]:
        lines.append(f"<strong>{stats['overdue_count']}</strong> facture(s) en retard ({fmt_money(stats['overdue_total'])}) : "
                     "Caffein s'occupe des relances.")
    return "Ton résumé hebdomadaire Caffein", _brand_email("Ta semaine en un coup d'œil", lines, "Ouvrir Caffein", "/")
