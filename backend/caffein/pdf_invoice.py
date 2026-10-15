# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rendu PDF A4 des factures et devis (remplace le couple HTML + Gotenberg).

Reprend la mise en page du nœud « Generate Invoice HTML » : en-tête émetteur,
bloc « Facturé à », tableau des prestations, totaux, pénalités et mentions légales.
"""

from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .utils import cents, fmt_date, fmt_money

INDIGO = colors.HexColor("#4f46e5")
INK = colors.HexColor("#111827")
TEXT = colors.HexColor("#1f2937")
BODY = colors.HexColor("#374151")
MUTED = colors.HexColor("#6b7280")
FAINT = colors.HexColor("#9ca3af")
LINE = colors.HexColor("#e5e7eb")
SOFT = colors.HexColor("#f9fafb")
HEAD = colors.HexColor("#f3f4f6")

_base = ParagraphStyle("base", fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=TEXT)
S = {
    "company": ParagraphStyle("company", parent=_base, fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=INK),
    "small": ParagraphStyle("small", parent=_base, fontSize=8.8, leading=12.5, textColor=MUTED),
    "title": ParagraphStyle("title", parent=_base, fontName="Helvetica-Bold", fontSize=24, leading=28, textColor=INDIGO, alignment=TA_RIGHT),
    "meta": ParagraphStyle("meta", parent=_base, fontSize=9.5, leading=14, textColor=BODY, alignment=TA_RIGHT),
    "label": ParagraphStyle("label", parent=_base, fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=FAINT),
    "client": ParagraphStyle("client", parent=_base, fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=INK),
    "th": ParagraphStyle("th", parent=_base, fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=MUTED),
    "th_r": ParagraphStyle("th_r", parent=_base, fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=MUTED, alignment=TA_RIGHT),
    "td": _base,
    "td_r": ParagraphStyle("td_r", parent=_base, alignment=TA_RIGHT),
    "tot_l": ParagraphStyle("tot_l", parent=_base, fontName="Helvetica-Bold", alignment=TA_RIGHT),
    "tot_r": ParagraphStyle("tot_r", parent=_base, alignment=TA_RIGHT),
    "grand": ParagraphStyle("grand", parent=_base, fontName="Helvetica-Bold", textColor=colors.white, alignment=TA_RIGHT),
    "body": ParagraphStyle("body", parent=_base, fontSize=9, leading=13, textColor=BODY),
    "legal": ParagraphStyle("legal", parent=_base, fontSize=7.5, leading=10.5, textColor=FAINT),
}


def _p(text: str, style: str) -> Paragraph:
    return Paragraph(text, S[style])


def _e(value: object) -> str:
    return escape(str(value or ""))


def _join(*parts: str) -> str:
    return "<br/>".join(p for p in parts if p)


def _client_name(client: dict | None) -> str:
    if not client:
        return "Client non renseigné"
    return client.get("name") or client.get("contact_name") or "Client"


def render_invoice_pdf(invoice: dict, client: dict | None, profile: dict, draft: bool = False) -> bytes:
    is_quote = invoice.get("kind") == "quote"
    vat_exempt = bool(invoice.get("vat_exempt"))
    vat_rate = float(invoice.get("vat_rate") or 0)
    sender = profile.get("company") or profile.get("full_name") or ""
    number = invoice.get("number") or "BROUILLON"

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm,
        title=f"{'Devis' if is_quote else 'Facture'} {number}", author=sender, creator="Caffein",
    )
    width = doc.width
    story = []

    # ── En-tête ──
    sender_lines = _join(
        _e(profile.get("full_name")) if profile.get("company") and profile.get("full_name") else "",
        _e(profile.get("address")),
        f"{_e(profile.get('zip_code'))} {_e(profile.get('city'))}".strip(),
        _e(profile.get("email")),
        _e(profile.get("phone")),
    )
    date_label = "Date d'émission" if not is_quote else "Date"
    due_label = "Validité" if is_quote else "Échéance"
    meta = _join(
        f"<b>N° :</b> {_e(number)}",
        f"<b>{date_label} :</b> {fmt_date(invoice.get('issued_at')) or '—'}",
        f"<b>{due_label} :</b> {fmt_date(invoice.get('due_date')) or '—'}",
    )
    header = Table(
        [[[_p(_e(sender), "company"), Spacer(1, 3), _p(sender_lines, "small")],
          [_p("DEVIS" if is_quote else "FACTURE", "title"), Spacer(1, 6), _p(meta, "meta")]]],
        colWidths=[width * 0.55, width * 0.45],
    )
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story += [header, Spacer(1, 10 * mm)]

    # ── Client ──
    client = client or {}
    client_lines = _join(
        _e(client.get("contact_name")) if client.get("contact_name") and client.get("contact_name") != client.get("name") else "",
        _e(client.get("address")),
        f"{_e(client.get('zip_code'))} {_e(client.get('city'))}".strip(),
        _e(client.get("email")),
        f"SIREN : {_e(client.get('siren'))}" if client.get("siren") else "",
        f"TVA : {_e(client.get('vat_number'))}" if client.get("vat_number") else "",
    )
    client_box = Table(
        [[[_p("FACTURÉ À" if not is_quote else "DESTINATAIRE", "label"), Spacer(1, 3),
           _p(_e(_client_name(client)), "client"), _p(client_lines, "small")]]],
        colWidths=[width],
    )
    client_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SOFT), ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("ROUNDEDCORNERS", [5, 5, 5, 5]),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 11),
    ]))
    story += [client_box, Spacer(1, 6 * mm)]

    if invoice.get("title"):
        story += [_p(f"<b>Objet :</b> {_e(invoice['title'])}", "body"), Spacer(1, 4 * mm)]

    # ── Prestations ──
    rows = [[_p("DESCRIPTION", "th"), _p("QTÉ", "th_r"), _p("PRIX UNIT. HT", "th_r"), _p("TOTAL HT", "th_r")]]
    subtotal = 0.0
    for item in invoice.get("items") or []:
        qty = float(item.get("quantity") or 0)
        unit = float(item.get("unit_price") or 0)
        line_total = cents(qty * unit)
        subtotal += line_total
        qty_txt = f"{qty:g}".replace(".", ",")
        rows.append([_p(_e(item.get("description")), "td"), _p(qty_txt, "td_r"),
                     _p(fmt_money(unit), "td_r"), _p(fmt_money(line_total), "td_r")])
    items_table = Table(rows, colWidths=[width - 82 * mm, 18 * mm, 32 * mm, 32 * mm], repeatRows=1)
    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEAD),
        ("LINEBELOW", (0, 1), (-1, -1), 0.6, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [items_table, Spacer(1, 5 * mm)]

    # ── Totaux ──
    subtotal = cents(subtotal)
    vat_amount = 0.0 if vat_exempt else cents(subtotal * vat_rate)
    total = cents(subtotal + vat_amount)
    vat_label = "TVA" if vat_exempt else f"TVA ({vat_rate * 100:g} %)".replace(".", ",")
    totals = Table(
        [[_p("Sous-total HT", "tot_l"), _p(fmt_money(subtotal), "tot_r")],
         [_p(vat_label, "tot_l"), _p("Non applicable" if vat_exempt else fmt_money(vat_amount), "tot_r")],
         [_p("Total" if vat_exempt else "Total TTC", "grand"), _p(fmt_money(total), "grand")]],
        colWidths=[48 * mm, 38 * mm], hAlign="RIGHT",
    )
    totals.setStyle(TableStyle([
        ("BACKGROUND", (0, 2), (-1, 2), INDIGO), ("ROUNDEDCORNERS", [0, 0, 5, 5]),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 2), (-1, 2), 9), ("BOTTOMPADDING", (0, 2), (-1, 2), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [totals, Spacer(1, 8 * mm)]

    # ── Conditions & paiement ──
    terms = []
    if invoice.get("delivery_date"):
        label = "Date de livraison prévue" if is_quote else "Date de livraison / d'exécution"
        terms.append(f"<b>{label} :</b> {fmt_date(invoice['delivery_date'])}")
    terms.append("<b>Nature de l'opération :</b> prestation de services")
    if invoice.get("payment_conditions"):
        terms.append(f"<b>Conditions de paiement :</b> {_e(invoice['payment_conditions'])}")
    if not is_quote and profile.get("iban"):
        terms.append(f"<b>IBAN :</b> {_e(profile['iban'])}" + (f" &nbsp; <b>BIC :</b> {_e(profile['bic'])}" if profile.get("bic") else ""))
    if not is_quote:
        terms.append(f"<b>Référence à rappeler :</b> {_e(number)}")
    story += [_p(_join(*terms), "body"), Spacer(1, 4 * mm)]

    if invoice.get("notes"):
        story += [_p(_e(invoice["notes"]).replace("\n", "<br/>"), "body"), Spacer(1, 4 * mm)]

    if is_quote:
        sign = Table([[[_p("BON POUR ACCORD", "label"), Spacer(1, 3),
                        _p("Date et signature du client, précédées de la mention « Bon pour accord »", "small"),
                        Spacer(1, 18 * mm)]]], colWidths=[85 * mm], hAlign="RIGHT")
        sign.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, LINE), ("ROUNDEDCORNERS", [5, 5, 5, 5]),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 8)]))
        story += [sign, Spacer(1, 6 * mm)]

    # ── Pénalités & mentions légales ──
    legal = _join(
        f"{_e(sender)} — {_e(profile.get('legal_mention'))}" if profile.get("legal_mention") else _e(sender),
        f"SIRET : {_e(profile.get('siret'))}" if profile.get("siret") else "",
        f"Code NAF : {_e(profile.get('naf_code'))}" if profile.get("naf_code") else "",
        "TVA non applicable, art. 293 B du Code général des impôts" if vat_exempt
        else (f"N° TVA intracommunautaire : {_e(profile.get('vat_number'))}" if profile.get("vat_number") else ""),
    )
    rule = Table([[""]], colWidths=[width], rowHeights=[1])
    rule.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, -1), 0.6, LINE)]))
    footer = []
    if not is_quote:
        footer += [_p("En cas de retard de paiement, une pénalité de 3 fois le taux d'intérêt légal sera appliquée, "
                      "ainsi qu'une indemnité forfaitaire de 40 € pour frais de recouvrement (art. L.441-10 du Code de commerce). "
                      "Pas d'escompte pour paiement anticipé.", "legal"), Spacer(1, 3 * mm)]
    footer += [rule, Spacer(1, 2 * mm), _p(legal, "legal")]
    story.append(KeepTogether(footer))

    def _decorate(canvas, _doc):
        canvas.saveState()
        if draft:
            canvas.setFont("Helvetica-Bold", 78)
            canvas.setFillColor(colors.Color(0.31, 0.27, 0.9, alpha=0.07))
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(35)
            canvas.drawCentredString(0, 0, "BROUILLON")
            canvas.restoreState()
            canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(FAINT)
        canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, f"{number} — page {canvas.getPageNumber()}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_decorate, onLaterPages=_decorate)
    return buf.getvalue()


def render_supplier_invoice_pdf(supplier: dict, customer: dict, number: str, issued: str, due: str,
                                lines: list[tuple[str, float, float]], vat_rate: float) -> bytes:
    """Fausse facture fournisseur pour la démo (alimente « Factures à traiter »)."""
    invoice = {
        "kind": "invoice", "number": number, "issued_at": issued, "due_date": due,
        "items": [{"description": d, "quantity": q, "unit_price": u} for d, q, u in lines],
        "vat_exempt": vat_rate == 0, "vat_rate": vat_rate,
    }
    return render_invoice_pdf(invoice, customer, supplier)
