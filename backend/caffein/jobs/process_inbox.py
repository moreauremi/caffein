# SPDX-License-Identifier: AGPL-3.0-or-later
"""Traitement automatique des documents déposés.

Remplace le workflow n8n « Factures automatiques v0.2 – Caffein » :
recherche dans « Factures à traiter » → téléchargement → extraction du texte →
agent IA (fournisseur, date, HT, TVA, TTC, catégorie, résumé, échéance, type)
→ renommage FOURNISSEUR-date → rangement dans un dossier par fournisseur
(créé si besoin) → insertion chiffrée en base (ex-« Supabase - Insert facture »).

    python -m caffein run process_inbox
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from .. import ai, config, services
from ..utils import slugify_name, today, unique_path
from . import every, job

log = logging.getLogger("caffein.jobs.inbox")

SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}


def extract_pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:20])
    except Exception as exc:  # PDF corrompu ou chiffré
        log.warning("Lecture PDF impossible (%s) : %s", path.name, exc)
        return ""


def _set_aside(path: Path, reason: str) -> dict:
    dest = unique_path(config.FOLDERS["ne_pas_trier"] / path.name)
    shutil.move(str(path), dest)
    return {"ok": False, "file": path.name, "reason": reason, "moved_to": "Ne pas trier"}


def _is_duplicate(data: dict) -> bool:
    for doc in services.list_documents():
        if (doc["fournisseur"] == data["fournisseur"] and doc["date"] == data["date"]
                and abs(doc["ttc"] - data["ttc"]) < 0.01 and doc["source"] != "invoice"):
            return True
    return False


def process_file(path: Path, profile: dict, source: str = "inbox", original_name: str | None = None) -> dict:
    if path.suffix.lower() not in SUPPORTED:
        return _set_aside(path, "Format non pris en charge (PDF, PNG, JPG ou WEBP attendus)")

    text = extract_pdf_text(path) if path.suffix.lower() == ".pdf" else ""
    try:
        data = ai.extract_document(path, text, profile)
    except ai.AIUnavailable as exc:
        return _set_aside(path, str(exc))

    if not data["ttc"] and not data["ht"]:
        return _set_aside(path, "Montants introuvables dans le document")
    if not data["fournisseur"]:
        data["fournisseur"] = "INCONNU"
    if not data["date"]:
        data["date"] = today().isoformat()
    if _is_duplicate(data):
        return _set_aside(path, "Doublon : ce document est déjà classé")

    supplier = slugify_name(data["fournisseur"])
    root = config.FOLDERS["recues" if data["tva_type"] == "deductible" else "envoyees"]
    dest = unique_path(root / supplier / f"{supplier}-{data['date']}{path.suffix.lower()}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), dest)

    doc_id = services.add_document({**data, "file_path": dest, "original_name": original_name or path.name, "source": source})
    return {"ok": True, "id": doc_id, "file": original_name or path.name, "stored_as": str(dest.relative_to(config.DRIVE_DIR)),
            **{k: data[k] for k in ("fournisseur", "date", "ht", "tva", "ttc", "categorie", "tva_type", "extracted_by")}}


@job(
    "process_inbox",
    title="Traitement des documents",
    description="Surveille « Factures à traiter », extrait les données avec l'IA, chiffre, renomme, "
                "range par fournisseur et alimente le suivi TVA.",
    replaces="Factures automatiques v0.2 – Caffein",
    schedule=every(minutes=1),
)
def run(files: list[str] | None = None, source: str = "inbox", names: dict | None = None) -> dict:
    profile = services.get_profile()
    paths = [Path(f) for f in files] if files else services.inbox_files()
    results = [process_file(p, profile, source, (names or {}).get(str(p))) for p in paths if p.exists()]
    if not results:
        return {"summary": "Aucun document à traiter", "quiet": True, "processed": 0, "results": []}

    ok = [r for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]
    parts = []
    if ok:
        parts.append(f"{len(ok)} document{'s' if len(ok) > 1 else ''} classé{'s' if len(ok) > 1 else ''}")
    if failed:
        parts.append(f"{len(failed)} mis de côté")
    return {
        "status": "success" if ok or not failed else "warning",
        "summary": " · ".join(parts) + (f" ({', '.join(r['fournisseur'] for r in ok[:3])})" if ok else ""),
        "notable": True, "processed": len(ok), "failed": len(failed), "results": results,
    }
