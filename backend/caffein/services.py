# SPDX-License-Identifier: AGPL-3.0-or-later
"""Logique métier : profil, clients, factures/devis, documents, tableaux de bord."""

from __future__ import annotations

import math
import secrets
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from . import config, crypto, db, fiscal
from .core.errors import Conflict, NotFound  # noqa: F401 (services.NotFound et services.Conflict restent valables)
from .utils import add_months, month_end, parse_date, slugify_name, today

# ═════════════════════════════════════════════════════════════════════════
# Profil
# ═════════════════════════════════════════════════════════════════════════
PROFILE_BOOL = {"versement_liberatoire", "vat_exempt", "notif_tva", "notif_echeance", "notif_hebdo", "notif_onboarding",
                "newsletter", "onboarding_done"}
PROFILE_EDITABLE = {
    "full_name", "company", "email", "phone", "address", "zip_code", "city", "siret", "naf_code", "iban", "bic",
    "legal_mention", "activity", "declaration_frequency", "versement_liberatoire", "vat_exempt", "vat_number",
    "default_vat_rate", "payment_terms_days", "invoice_prefix", "notif_tva", "notif_echeance", "notif_hebdo",
    "tva_alert_threshold", "newsletter", "notif_onboarding",
}


def get_profile() -> dict:
    row = db.fetch_one("SELECT * FROM profile WHERE id = 1")
    if row is None:
        db.insert("profile", {"id": 1, "created_at": db.now_iso()})
        row = db.fetch_one("SELECT * FROM profile WHERE id = 1")
    for key in PROFILE_BOOL:
        row[key] = bool(row[key])
    return row


def update_profile(values: dict) -> dict:
    clean = {}
    for key, value in values.items():
        if key not in PROFILE_EDITABLE:
            continue
        if key in PROFILE_BOOL:
            value = int(bool(value))
        elif key == "activity" and value not in fiscal.ACTIVITIES:
            raise ValueError("Activité inconnue")
        elif key == "declaration_frequency" and value not in ("monthly", "quarterly"):
            raise ValueError("Périodicité inconnue")
        elif key in ("default_vat_rate", "tva_alert_threshold"):
            value = float(value)
        elif key == "payment_terms_days":
            value = max(0, min(int(value), 60))  # délai légal max : 60 jours
        else:
            value = str(value or "").strip()
        clean[key] = value
    db.update("profile", 1, clean)
    return get_profile()


# ═════════════════════════════════════════════════════════════════════════
# Clients
# ═════════════════════════════════════════════════════════════════════════
CLIENT_FIELDS = ("name", "contact_name", "email", "phone", "address", "zip_code", "city", "siren", "vat_number", "notes")


def list_clients() -> list[dict]:
    return db.fetch_all("""
        SELECT c.*,
               COUNT(i.id) FILTER (WHERE i.kind = 'invoice' AND i.status != 'draft') AS invoice_count,
               COALESCE(SUM(i.total) FILTER (WHERE i.kind = 'invoice' AND i.status = 'paid'), 0) AS total_paid
        FROM clients c LEFT JOIN invoices i ON i.client_id = c.id
        GROUP BY c.id ORDER BY c.name COLLATE NOCASE""")


def get_client(client_id: int | None) -> dict | None:
    if client_id is None:
        return None
    return db.fetch_one("SELECT * FROM clients WHERE id = ?", (client_id,))


def create_client(data: dict) -> dict:
    values = {k: str(data.get(k) or "").strip() for k in CLIENT_FIELDS}
    if not values["name"]:
        raise ValueError("Le nom du client est obligatoire")
    values["created_at"] = db.now_iso()
    return get_client(db.insert("clients", values))


def update_client(client_id: int, data: dict) -> dict:
    if not get_client(client_id):
        raise NotFound("Client introuvable")
    values = {k: str(data.get(k) or "").strip() for k in CLIENT_FIELDS if k in data}
    if "name" in values and not values["name"]:
        raise ValueError("Le nom du client est obligatoire")
    db.update("clients", client_id, values)
    return get_client(client_id)


def delete_client(client_id: int) -> None:
    used = db.fetch_one("SELECT COUNT(*) AS n FROM invoices WHERE client_id = ? AND status != 'draft'", (client_id,))
    if used and used["n"]:
        raise Conflict("Ce client a des factures émises : il ne peut pas être supprimé.")
    try:
        db.execute("DELETE FROM clients WHERE id = ?", (client_id,))
    except sqlite3.IntegrityError as exc:  # commandes clients ou autres fiches liées
        raise Conflict("Ce client est utilisé ailleurs (commandes…) : il ne peut pas être supprimé.") from exc


def find_or_create_client(name: str, contact: str = "", email: str | None = None) -> dict | None:
    name = (name or "").strip()
    if not name:
        return None
    row = db.fetch_one("SELECT * FROM clients WHERE lower(name) = lower(?) OR lower(contact_name) = lower(?)", (name, name))
    if row:
        return row
    return create_client({"name": name, "contact_name": contact or "", "email": email or ""})


# ═════════════════════════════════════════════════════════════════════════
# Factures & devis
# ═════════════════════════════════════════════════════════════════════════
INVOICE_STATUSES = {"invoice": {"draft", "pending", "paid", "cancelled"},
                    "quote": {"draft", "pending", "accepted", "refused", "invoiced"}}


def compute_totals(items: list[dict], vat_exempt: bool, vat_rate: float) -> tuple[float, float, float]:
    subtotal = round(sum(line_amount(i) for i in items), 2)
    vat = 0.0 if vat_exempt else round(subtotal * float(vat_rate or 0), 2)
    return subtotal, vat, round(subtotal + vat, 2)


def line_amount(item: dict) -> float:
    return round(float(item.get("quantity") or 0) * float(item.get("unit_price") or 0), 2)


def _number(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} : nombre attendu.")
    try:
        number = float(str(value).replace(",", ".").replace(" ", "")) if value not in (None, "") else 0.0
    except (TypeError, ValueError):
        raise ValueError(f"{label} : nombre attendu.") from None
    if not math.isfinite(number) or abs(number) > 1e9:
        raise ValueError(f"{label} : nombre hors limites.")
    return number


def _clean_items(items: object) -> list[dict]:
    """Lignes reçues → lignes à enregistrer (description, quantité, prix unitaire, article facultatif)."""
    if items is None:
        return []
    if not isinstance(items, list):
        raise ValueError("Lignes invalides.")
    if len(items) > 200:
        raise ValueError("200 lignes au plus.")
    clean = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Lignes invalides.")
        desc = str(item.get("description") or "").strip()
        if not desc:
            continue
        line = {
            "description": desc[:300],
            "quantity": round(_number(item.get("quantity"), "Quantité"), 3),
            "unit_price": round(_number(item.get("unit_price"), "Prix unitaire"), 2),
            "article_id": None,
        }
        article = item.get("article_id")
        if article not in (None, "") and not isinstance(article, bool):
            try:
                line["article_id"] = int(article)
            except (TypeError, ValueError):
                raise ValueError("Article invalide.") from None
        clean.append(line)
    _check_articles(clean)
    return clean


def _check_articles(lines: list[dict]) -> None:
    """Article du catalogue (Données techniques) : vérifié si le module est actif, ignoré sinon."""
    from .core import modules as registry

    ids = {line["article_id"] for line in lines if line.get("article_id")}
    if not ids:
        return
    if not registry.is_enabled("technical"):
        for line in lines:
            line["article_id"] = None
        return
    found = {r["id"] for r in db.fetch_all(f"SELECT id FROM technical_articles WHERE id IN ({', '.join('?' for _ in ids)})",
                                           tuple(ids))}
    if ids - found:
        raise ValueError("Article introuvable dans les données techniques.")


def invoice_lines(invoice_ids: list[int] | None = None, kind: str | None = None) -> dict[int, list[dict]]:
    """Lignes des factures et devis (table invoice_lines), regroupées par document, dans l'ordre."""
    sql = ("SELECT l.invoice_id, l.article_id, l.description, l.quantity, l.unit_price FROM invoice_lines l "
           "JOIN invoices i ON i.id = l.invoice_id")
    params: tuple = ()
    if invoice_ids is not None:
        if not invoice_ids:
            return {}
        sql += f" WHERE l.invoice_id IN ({', '.join('?' for _ in invoice_ids)})"
        params = tuple(invoice_ids)
    elif kind:
        sql += " WHERE i.kind = ?"
        params = (kind,)
    out: dict[int, list[dict]] = {}
    for row in db.fetch_all(sql + " ORDER BY l.invoice_id, l.position, l.id", params):
        invoice_id = row.pop("invoice_id")
        row["amount"] = line_amount(row)
        out.setdefault(invoice_id, []).append(row)
    return out


def _write_lines(conn, invoice_id: int, items: list[dict]) -> None:
    conn.execute("DELETE FROM invoice_lines WHERE invoice_id = ?", (invoice_id,))
    conn.executemany(
        "INSERT INTO invoice_lines (invoice_id, position, article_id, description, quantity, unit_price) VALUES (?, ?, ?, ?, ?, ?)",
        [(invoice_id, position, i.get("article_id"), i["description"], i["quantity"], i["unit_price"])
         for position, i in enumerate(items)])


def preview_totals(data: dict) -> dict:
    """Totaux d'un document en cours de saisie, calculés par le serveur (l'interface ne fait qu'afficher)."""
    profile = get_profile()
    items = _clean_items(data.get("items"))
    vat_exempt = bool(data.get("vat_exempt", profile["vat_exempt"]))
    vat_rate = _number(data.get("vat_rate", profile["default_vat_rate"]), "Taux de TVA")
    subtotal, vat_amount, total = compute_totals(items, vat_exempt, vat_rate)
    return {"subtotal": subtotal, "vat_amount": vat_amount, "total": total,
            "lines": [line_amount(i) for i in _clean_items_keep_positions(data.get("items"))]}


def _clean_items_keep_positions(items: object) -> list[dict]:
    """Comme _clean_items, mais une ligne sans description compte pour 0 (aperçu ligne à ligne)."""
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            out.append({})
            continue
        try:
            out.append({"quantity": _number(item.get("quantity"), "Quantité"),
                        "unit_price": _number(item.get("unit_price"), "Prix unitaire")})
        except ValueError:
            out.append({})
    return out


def portal_url(invoice: dict) -> str:
    return f"{config.APP_URL}/f/{invoice['public_token']}"


def display_status(inv: dict, ref: date | None = None) -> str:
    ref = ref or today()
    if inv["kind"] == "invoice" and inv["status"] == "pending":
        due = parse_date(inv.get("due_date"))
        if due and due < ref:
            return "overdue"
    return inv["status"]


def _hydrate(inv: dict, ref: date | None = None, lines: dict[int, list[dict]] | None = None) -> dict:
    ref = ref or today()
    inv["items"] = (lines if lines is not None else invoice_lines([inv["id"]])).get(inv["id"], [])
    inv["vat_exempt"] = bool(inv["vat_exempt"])
    inv["display_status"] = display_status(inv, ref)
    due = parse_date(inv.get("due_date"))
    inv["days_overdue"] = (ref - due).days if inv["display_status"] == "overdue" and due else 0
    inv["portal_url"] = portal_url(inv)
    inv["has_pdf"] = bool(inv.get("pdf_path") and Path(inv["pdf_path"]).exists())
    return inv


def list_invoices(kind: str | None = None) -> list[dict]:
    sql = """SELECT i.*, c.name AS client_name, c.email AS client_email
             FROM invoices i LEFT JOIN clients c ON c.id = i.client_id"""
    params: tuple = ()
    if kind:
        sql += " WHERE i.kind = ?"
        params = (kind,)
    sql += " ORDER BY COALESCE(i.issued_at, i.created_at) DESC, i.id DESC"
    ref = today()
    lines = invoice_lines(kind=kind)
    return [_hydrate(row, ref, lines) for row in db.fetch_all(sql, params)]


def get_invoice(invoice_id: int) -> dict:
    row = db.fetch_one("SELECT * FROM invoices WHERE id = ?", (invoice_id,))
    if not row:
        raise NotFound("Facture introuvable")
    inv = _hydrate(row)
    from .core.entities import ref_label  # libellé de l'article choisi sur une ligne (module Données techniques)

    for line in inv["items"]:
        line["article_label"] = ref_label("technical.articles", line.get("article_id"))
    inv["client"] = get_client(inv.get("client_id"))
    inv["client_name"] = inv["client"]["name"] if inv["client"] else ""
    inv["emails"] = db.fetch_all(
        "SELECT id, kind, to_email, subject, status, created_at FROM emails WHERE invoice_id = ? ORDER BY id DESC", (invoice_id,))
    return inv


def get_invoice_by_token(token: str) -> dict:
    row = db.fetch_one("SELECT id FROM invoices WHERE public_token = ?", (token,))
    if not row:
        raise NotFound("Document introuvable")
    inv = get_invoice(row["id"])
    if inv["status"] == "draft":
        raise NotFound("Document introuvable")
    return inv


def _invoice_values(data: dict, profile: dict, existing: dict | None = None) -> tuple[dict, list[dict] | None]:
    """Valeurs de la facture et lignes à enregistrer (None : lignes inchangées)."""
    base = existing or {}
    vat_exempt = bool(data.get("vat_exempt", base.get("vat_exempt", profile["vat_exempt"])))
    vat_rate = _number(data.get("vat_rate", base.get("vat_rate", profile["default_vat_rate"])), "Taux de TVA")
    if not 0 <= vat_rate <= 1:
        raise ValueError("Taux de TVA invalide.")
    items = _clean_items(data["items"]) if "items" in data else None
    subtotal, vat_amount, total = compute_totals(items if items is not None else base.get("items", []), vat_exempt, vat_rate)
    values = {
        "vat_exempt": int(vat_exempt), "vat_rate": vat_rate,
        "subtotal": subtotal, "vat_amount": vat_amount, "total": total, "updated_at": db.now_iso(),
    }
    for key in ("title", "notes", "payment_conditions"):
        if key in data:
            values[key] = str(data.get(key) or "").strip()
    for key in ("issued_at", "due_date", "delivery_date"):
        if key in data:
            d = parse_date(data.get(key))
            values[key] = d.isoformat() if d else None
    if "client_id" in data:
        cid = data.get("client_id")
        if cid not in (None, "") and not get_client(int(cid)):
            raise ValueError("Client introuvable")
        values["client_id"] = int(cid) if cid not in (None, "") else None
    return values, items


def create_invoice(data: dict) -> dict:
    profile = get_profile()
    kind = data.get("kind", "invoice")
    if kind not in INVOICE_STATUSES:
        raise ValueError("Type de document inconnu")
    values, items = _invoice_values(data, profile)
    if not values.get("payment_conditions") and kind == "invoice":
        values["payment_conditions"] = f"Virement bancaire à {profile['payment_terms_days']} jours"
    values.update({
        "kind": kind, "status": "draft", "public_token": secrets.token_urlsafe(16),
        "source_text": str(data.get("source_text") or ""), "source_quote_id": data.get("source_quote_id"),
        "created_at": db.now_iso(),
    })
    with db.connect() as conn:  # la facture et ses lignes dans la même transaction
        cols = ", ".join(values)
        invoice_id = conn.execute(f"INSERT INTO invoices ({cols}) VALUES ({', '.join(':' + k for k in values)})",
                                  values).lastrowid
        _write_lines(conn, invoice_id, items or [])
    return get_invoice(invoice_id)


def update_invoice(invoice_id: int, data: dict) -> dict:
    inv = get_invoice(invoice_id)
    if inv["status"] != "draft":
        raise Conflict("Seuls les brouillons sont modifiables. Une facture émise ne peut plus être changée.")
    values, items = _invoice_values(data, get_profile(), inv)
    with db.connect() as conn:
        conn.execute(f"UPDATE invoices SET {', '.join(f'{k} = :{k}' for k in values)} WHERE id = :_id",
                     {**values, "_id": invoice_id})
        if items is not None:
            _write_lines(conn, invoice_id, items)
    return get_invoice(invoice_id)


def delete_invoice(invoice_id: int) -> None:
    inv = get_invoice(invoice_id)
    if inv["status"] != "draft":
        raise Conflict("Seuls les brouillons peuvent être supprimés (numérotation continue obligatoire).")
    db.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))


def next_number(kind: str, year: int, prefix: str) -> str:
    stem = f"{prefix if kind == 'invoice' else 'DEVIS'}-{year}-"
    row = db.fetch_one("SELECT number FROM invoices WHERE kind = ? AND number LIKE ? ORDER BY number DESC LIMIT 1",
                       (kind, stem + "%"))
    seq = int(row["number"].rsplit("-", 1)[1]) + 1 if row else 1
    return f"{stem}{seq:05d}"


def finalize_invoice(invoice_id: int) -> dict:
    """Émet le document : numéro définitif, dates, statut « en attente », PDF."""
    inv = get_invoice(invoice_id)
    if inv["status"] != "draft":
        return inv
    if not inv["items"] or inv["total"] <= 0:
        raise ValueError("Ajoutez au moins une ligne avec un montant avant d'émettre.")
    if not inv.get("client_id"):
        raise ValueError("Choisissez un client avant d'émettre.")
    profile = get_profile()
    issued = parse_date(inv.get("issued_at")) or today()
    due = parse_date(inv.get("due_date")) or (issued + timedelta(days=profile["payment_terms_days"] if inv["kind"] == "invoice" else 30))
    number = next_number(inv["kind"], issued.year, profile["invoice_prefix"] or "CAFFEIN")
    db.update("invoices", invoice_id, {"number": number, "issued_at": issued.isoformat(), "due_date": due.isoformat(),
                                       "status": "pending", "updated_at": db.now_iso()})

    from .jobs import run_job  # import local : évite l'import circulaire

    run_job("generate_pdf", trigger="event", invoice_id=invoice_id)
    return get_invoice(invoice_id)


def invoice_pdf_target(inv: dict) -> Path:
    client_folder = slugify_name(inv.get("client_name") or "SANS CLIENT")
    prefix = "devis" if inv["kind"] == "quote" else "facture"
    return config.FOLDERS["envoyees"] / client_folder / f"{prefix}-{inv['number']}.pdf"


def render_pdf_bytes(invoice_id: int) -> tuple[bytes, str]:
    """PDF à la volée (brouillon = filigrane). Renvoie (contenu, nom de fichier)."""
    from .pdf_invoice import render_invoice_pdf

    inv = get_invoice(invoice_id)
    if inv["status"] != "draft" and inv["has_pdf"]:
        path = Path(inv["pdf_path"])
        return path.read_bytes(), path.name
    data = render_invoice_pdf(inv, inv["client"], get_profile(), draft=inv["status"] == "draft")
    prefix = "devis" if inv["kind"] == "quote" else "facture"
    return data, f"{prefix}-{inv.get('number') or 'brouillon'}.pdf"


def mark_paid(invoice_id: int, paid_at: str | None = None) -> dict:
    inv = get_invoice(invoice_id)
    if inv["kind"] != "invoice" or inv["status"] not in ("pending",):
        raise Conflict("Seule une facture émise en attente peut être marquée payée.")
    paid = parse_date(paid_at) or today()
    db.update("invoices", invoice_id, {"status": "paid", "paid_at": paid.isoformat(), "updated_at": db.now_iso()})
    # TVA sur les encaissements (prestations de services) : la TVA collectée
    # est exigible à la date du paiement → document « collectée » daté du paiement.
    add_document({
        "date": paid.isoformat(), "fournisseur": (inv["client_name"] or "CLIENT").upper(),
        "ht": inv["subtotal"], "tva": inv["vat_amount"], "ttc": inv["total"], "categorie": "Prestations",
        "resume": f"Encaissement facture {inv['number']}"[:80], "tva_type": "collected", "echeance": inv.get("due_date"),
        "file_path": inv.get("pdf_path"), "original_name": Path(inv["pdf_path"]).name if inv.get("pdf_path") else "",
        "source": "invoice", "invoice_id": invoice_id, "extracted_by": "caffein",
    })
    return get_invoice(invoice_id)


def cancel_invoice(invoice_id: int) -> dict:
    inv = get_invoice(invoice_id)
    if inv["kind"] != "invoice" or inv["status"] not in ("pending", "paid"):
        raise Conflict("Cette facture ne peut pas être annulée.")
    db.update("invoices", invoice_id, {"status": "cancelled", "updated_at": db.now_iso()})
    db.execute("DELETE FROM documents WHERE invoice_id = ?", (invoice_id,))
    return get_invoice(invoice_id)


def set_quote_status(invoice_id: int, status: str) -> dict:
    inv = get_invoice(invoice_id)
    if inv["kind"] != "quote" or status not in ("accepted", "refused", "pending"):
        raise Conflict("Statut de devis invalide.")
    if inv["status"] in ("draft", "invoiced"):
        raise Conflict("Ce devis doit d'abord être émis." if inv["status"] == "draft" else "Ce devis a déjà été facturé.")
    db.update("invoices", invoice_id, {"status": status, "updated_at": db.now_iso()})
    return get_invoice(invoice_id)


def convert_quote(invoice_id: int) -> dict:
    quote = get_invoice(invoice_id)
    if quote["kind"] != "quote" or quote["status"] not in ("pending", "accepted"):
        raise Conflict("Seul un devis émis ou accepté peut être transformé en facture.")
    invoice = create_invoice({
        "kind": "invoice", "client_id": quote["client_id"], "title": quote["title"],
        "items": [{k: line[k] for k in ("description", "quantity", "unit_price", "article_id")} for line in quote["items"]],
        "vat_exempt": quote["vat_exempt"], "vat_rate": quote["vat_rate"], "delivery_date": quote.get("delivery_date"),
        "notes": f"Suite au devis n° {quote['number']}.", "source_quote_id": invoice_id,
    })
    db.update("invoices", invoice_id, {"status": "invoiced", "updated_at": db.now_iso()})
    return invoice


def invoice_summary() -> dict:
    ref = today()
    invoices = [i for i in list_invoices("invoice")]
    pending = [i for i in invoices if i["display_status"] in ("pending", "overdue")]
    overdue = [i for i in invoices if i["display_status"] == "overdue"]
    month_start = ref.replace(day=1)
    paid_month = [i for i in invoices if i["status"] == "paid" and (parse_date(i["paid_at"]) or date.min) >= month_start]
    quotes = [q for q in list_invoices("quote") if q["status"] == "pending"]
    return {
        "to_collect": round(sum(i["total"] for i in pending), 2), "to_collect_count": len(pending),
        "overdue_total": round(sum(i["total"] for i in overdue), 2), "overdue_count": len(overdue),
        "paid_month": round(sum(i["total"] for i in paid_month), 2), "paid_month_count": len(paid_month),
        "quotes_pending": round(sum(q["total"] for q in quotes), 2), "quotes_pending_count": len(quotes),
        "drafts": sum(1 for i in invoices if i["status"] == "draft"),
    }


# ═════════════════════════════════════════════════════════════════════════
# Documents classés (champs sensibles chiffrés)
# ═════════════════════════════════════════════════════════════════════════
ENCRYPTED = ("fournisseur", "ht", "tva", "ttc", "categorie", "resume")


def _decrypt_doc(row: dict) -> dict:
    for key in ("fournisseur", "categorie", "resume"):
        row[key] = crypto.decrypt(row[key])
    for key in ("ht", "tva", "ttc"):
        row[key] = crypto.decrypt_float(row[key])
    row["has_file"] = bool(row.get("file_path") and Path(row["file_path"]).exists())
    return row


def add_document(fields: dict) -> int:
    values = {k: crypto.encrypt(fields.get(k)) for k in ENCRYPTED}
    values.update({
        "date": fields.get("date"), "tva_type": fields["tva_type"], "echeance": fields.get("echeance"),
        "file_path": str(fields["file_path"]) if fields.get("file_path") else None,
        "original_name": fields.get("original_name", ""), "source": fields.get("source", "inbox"),
        "invoice_id": fields.get("invoice_id"), "extracted_by": fields.get("extracted_by", ""),
        "created_at": fields.get("created_at") or db.now_iso(),
    })
    return db.insert("documents", values)


def list_documents(start: date | None = None, end: date | None = None) -> list[dict]:
    sql, params = "SELECT * FROM documents", []
    if start and end:
        sql += " WHERE date BETWEEN ? AND ?"
        params = [start.isoformat(), end.isoformat()]
    sql += " ORDER BY date DESC, id DESC"
    return [_decrypt_doc(r) for r in db.fetch_all(sql, tuple(params))]


def get_document(doc_id: int) -> dict:
    row = db.fetch_one("SELECT * FROM documents WHERE id = ?", (doc_id,))
    if not row:
        raise NotFound("Document introuvable")
    return _decrypt_doc(row)


def update_document(doc_id: int, data: dict) -> dict:
    doc = get_document(doc_id)
    if doc["source"] == "invoice":
        raise Conflict("Ce document provient d'une facture Caffein : modifiez la facture elle-même.")
    values = {}
    for key in ENCRYPTED:
        if key in data:
            values[key] = crypto.encrypt(data[key])
    if "date" in data:
        d = parse_date(data["date"])
        values["date"] = d.isoformat() if d else None
    if data.get("tva_type") in ("collected", "deductible"):
        values["tva_type"] = data["tva_type"]
    db.update("documents", doc_id, values)
    return get_document(doc_id)


def delete_document(doc_id: int, delete_file: bool = True) -> None:
    doc = get_document(doc_id)
    if doc["source"] == "invoice":
        raise Conflict("Ce document provient d'une facture Caffein : annulez la facture pour le retirer.")
    db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    if delete_file and doc.get("file_path"):
        path = Path(doc["file_path"])
        if path.exists() and config.DRIVE_DIR in path.resolve().parents:
            path.unlink()


# ═════════════════════════════════════════════════════════════════════════
# Tableaux de bord
# ═════════════════════════════════════════════════════════════════════════
def time_saved_minutes() -> int:
    docs = db.fetch_one("SELECT COUNT(*) AS n FROM documents WHERE source != 'invoice'")["n"]
    invoices = db.fetch_one("SELECT COUNT(*) AS n FROM invoices WHERE status != 'draft'")["n"]
    reminders = db.fetch_one("SELECT COUNT(*) AS n FROM emails WHERE kind = 'reminder' AND status != 'failed'")["n"]
    return docs * config.MINUTES_PER_DOCUMENT + invoices * config.MINUTES_PER_INVOICE + reminders * config.MINUTES_PER_REMINDER


def _tva_totals(docs: list[dict]) -> tuple[float, float]:
    collected = round(sum(d["tva"] for d in docs if d["tva_type"] == "collected"), 2)
    deductible = round(sum(d["tva"] for d in docs if d["tva_type"] == "deductible"), 2)
    return collected, deductible


def tva_dashboard(kind: str) -> dict:
    ref = today()
    period = fiscal.tva_period(kind, ref)
    docs = list_documents(period.start, period.end)
    collected, deductible = _tva_totals(docs)

    months = fiscal.tva_chart_months(kind, ref)
    chart_docs = list_documents(months[0], month_end(months[-1]))
    chart = []
    for m in months:
        bucket = [d for d in chart_docs if d["date"] and d["date"][:7] == m.isoformat()[:7]]
        c, dd = _tva_totals(bucket)
        chart.append({"period": fiscal.month_label_short(m), "collected": c, "deductible": dd})

    deadline = fiscal.tva_deadline(period.end)
    return {
        "period": period.as_dict(),
        "metrics": {
            "documents": len([d for d in docs if d["source"] != "invoice"]),
            "time_saved_min": len([d for d in docs if d["source"] != "invoice"]) * config.MINUTES_PER_DOCUMENT,
            "collected": collected, "deductible": deductible, "balance": round(collected - deductible, 2),
            "ratio": round(deductible / collected, 4) if collected else (1.0 if deductible else 0.0),
            "ht_sales": round(sum(d["ht"] for d in docs if d["tva_type"] == "collected"), 2),
            "ht_purchases": round(sum(d["ht"] for d in docs if d["tva_type"] == "deductible"), 2),
        },
        "deadline": {"date": deadline.isoformat(), "days_left": (deadline - ref).days},
        "chart": chart,
        "recent": list_documents()[:5],
        "vat_exempt": get_profile()["vat_exempt"],
    }


def home_dashboard() -> dict:
    ref = today()
    month = fiscal.tva_period("month", ref)
    docs_month = list_documents(month.start, month.end)
    collected, deductible = _tva_totals(docs_month)
    summary = invoice_summary()
    activity = db.fetch_all("""
        SELECT id, job, summary, status, started_at FROM job_runs
        WHERE json_extract(details, '$.notable') = 1 OR status = 'error'
        ORDER BY started_at DESC, id DESC LIMIT 6""")
    return {
        "stats": {
            "documents": db.fetch_one("SELECT COUNT(*) AS n FROM documents WHERE source != 'invoice'")["n"],
            "tva_collected": collected, "balance": round(collected - deductible, 2),
            "time_saved_min": time_saved_minutes(),
            **{k: summary[k] for k in ("to_collect", "to_collect_count", "overdue_total", "overdue_count", "paid_month")},
        },
        "notifications": list_notifications(),
        "activity": activity,
        "inbox_count": len(inbox_files()),
        "next_deadlines": upcoming_deadlines(ref)[:3],
    }


def list_notifications() -> list[dict]:
    return db.fetch_all("SELECT * FROM notifications ORDER BY created_at DESC, id DESC LIMIT ?", (config.NOTIFICATIONS_KEPT,))


def inbox_files() -> list[Path]:
    if not config.INBOX_DIR.exists():
        return []
    return sorted(p for p in config.INBOX_DIR.iterdir() if p.is_file() and not p.name.startswith("."))


# ── URSSAF ───────────────────────────────────────────────────────────────
def urssaf_dashboard(year: int | None = None) -> dict:
    ref = today()
    year = year or ref.year
    profile = get_profile()
    info = fiscal.activity_info(profile["activity"])
    rate = fiscal.contribution_rate(profile["activity"], profile["versement_liberatoire"])

    paid = db.fetch_all("SELECT subtotal, paid_at FROM invoices WHERE kind = 'invoice' AND status = 'paid' AND paid_at LIKE ?",
                        (f"{year}-%",))
    monthly = [0.0] * 12
    for row in paid:
        d = parse_date(row["paid_at"])
        monthly[d.month - 1] += row["subtotal"]
    monthly = [round(v, 2) for v in monthly]

    declared = {r["period_key"]: r["declared_at"] for r in db.fetch_all("SELECT * FROM declarations")}
    tracked_from = parse_date(profile.get("created_at"))
    periods = []
    for p in fiscal.declaration_periods(year, profile["declaration_frequency"]):
        ca = round(sum(monthly[m - 1] for m in range(p.start.month, p.end.month + 1)), 2)
        deadline = fiscal.declaration_deadline(p)
        status = fiscal.declaration_status(p, deadline, p.key in declared, ref, tracked_from)
        periods.append({**p.as_dict(), "ca": ca, "contributions": round(ca * rate, 2), "deadline": deadline.isoformat(),
                        "days_left": (deadline - ref).days, "status": status, "declared_at": declared.get(p.key)})

    ca_year = round(sum(monthly), 2)
    pending = db.fetch_one("SELECT COALESCE(SUM(subtotal), 0) AS s FROM invoices WHERE kind = 'invoice' AND status = 'pending'")["s"]
    open_periods = sorted((p for p in periods if p["status"] in ("late", "to_declare", "in_progress")), key=lambda p: p["deadline"])
    return {
        "year": year,
        "activity": {"key": profile["activity"], **info, "total_rate": round(rate, 4),
                     "versement_liberatoire": profile["versement_liberatoire"]},
        "frequency": profile["declaration_frequency"],
        "ca_year": ca_year, "contributions_year": round(ca_year * rate, 2), "net_year": round(ca_year * (1 - rate), 2),
        "pending_ht": round(pending, 2),
        "monthly": [{"month": fiscal.month_label_short(date(year, i + 1, 1)), "ca": v} for i, v in enumerate(monthly)],
        "periods": periods,
        "next": open_periods[0] if open_periods else None,
        "thresholds": {
            "plafond": info["plafond"], "plafond_ratio": round(ca_year / info["plafond"], 4),
            "franchise_tva": info["franchise_tva"], "franchise_ratio": round(ca_year / info["franchise_tva"], 4),
        },
    }


def set_declared(period_key: str, declared: bool) -> None:
    if declared:
        db.execute("INSERT OR REPLACE INTO declarations (period_key, declared_at) VALUES (?, ?)", (period_key, db.now_iso()))
    else:
        db.execute("DELETE FROM declarations WHERE period_key = ?", (period_key,))


def upcoming_deadlines(ref: date) -> list[dict]:
    """Prochaines échéances : TVA (20 du mois suivant) et déclaration URSSAF."""
    items = []
    profile = get_profile()
    if not profile["vat_exempt"]:
        month = fiscal.tva_period("month", add_months(ref.replace(day=1), -1))
        deadline = fiscal.tva_deadline(month.end)
        if deadline < ref:
            deadline = fiscal.tva_deadline(fiscal.tva_period("month", ref).end)
            month = fiscal.tva_period("month", ref)
        docs = list_documents(month.start, month.end)
        c, d = _tva_totals(docs)
        items.append({"type": "tva", "label": f"TVA — {month.label}", "date": deadline.isoformat(),
                      "days_left": (deadline - ref).days, "amount": round(c - d, 2), "path": "/comptabilite/tva"})
    urssaf = urssaf_dashboard(ref.year)
    nxt = next((p for p in urssaf["periods"] if p["status"] in ("late", "to_declare")), None)
    if nxt is None and urssaf["next"]:
        nxt = urssaf["next"]
    if nxt:
        items.append({"type": "urssaf", "label": f"Déclaration URSSAF — {nxt['label']}", "date": nxt["deadline"],
                      "days_left": nxt["days_left"], "amount": nxt["contributions"], "path": "/comptabilite/urssaf",
                      "status": nxt["status"]})
    return sorted(items, key=lambda x: x["date"])

