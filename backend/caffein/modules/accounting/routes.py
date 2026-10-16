# SPDX-License-Identifier: AGPL-3.0-or-later
"""Routes de la Comptabilité : TVA, URSSAF, justificatifs et dossiers de classement."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import Body, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse

from ... import config, services
from ...core.deps import current_user, module_router
from ...jobs import run_job
from ...jobs.setup_drive import tree as drive_tree
from ...utils import unique_path

router = module_router("accounting")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@router.get("/tva")
def tva(period: str = Query("month", pattern="^(month|quarter|year)$")) -> dict:
    return services.tva_dashboard(period)


@router.get("/urssaf")
def urssaf(year: int | None = Query(None, ge=2000, le=2100)) -> dict:
    return services.urssaf_dashboard(year)


@router.post("/urssaf/declarations")
def urssaf_declare(payload: dict = Body(...)) -> dict:
    key = str(payload.get("period_key", ""))
    if not re.fullmatch(r"\d{4}-(\d{2}|T[1-4])", key):
        raise ValueError("Période invalide")
    services.set_declared(key, bool(payload.get("declared", True)))
    return services.urssaf_dashboard(int(key[:4]))


# ── Justificatifs ────────────────────────────────────────────────────────
@router.get("/documents")
def documents() -> list[dict]:
    return services.list_documents()


@router.post("/documents/upload")
def upload_documents(files: list[UploadFile] = File(...), user: dict = Depends(current_user)) -> dict:
    saved, names = [], {}
    config.INBOX_DIR.mkdir(parents=True, exist_ok=True)
    for upload in files:
        original = Path(upload.filename or "document").name
        content = upload.file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"{original} dépasse 20 Mo")
        clean = re.sub(r"[^\w.\- ()À-ÿ]", "_", original)[:120] or "document"
        target = unique_path(config.INBOX_DIR / clean)
        target.write_bytes(content)
        saved.append(str(target))
        names[str(target)] = original
    run = run_job("process_inbox", trigger="upload", actor=user["email"], files=saved, source="upload", names=names)
    return {"run": run}


@router.put("/documents/{doc_id}")
def update_document(doc_id: int, data: dict = Body(...)) -> dict:
    return services.update_document(doc_id, data)


@router.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: int) -> Response:
    services.delete_document(doc_id)
    return Response(status_code=204)


@router.get("/documents/{doc_id}/file")
def document_file(doc_id: int) -> FileResponse:
    doc = services.get_document(doc_id)
    if not doc["has_file"]:
        raise services.NotFound("Fichier introuvable")
    return _file_response(Path(doc["file_path"]))


# Affichés dans le navigateur : PDF et images seulement. Tout autre fichier (HTML, SVG… déposé ou mis de côté) est
# téléchargé, jamais affiché : servi depuis l'adresse de Caffein, il pourrait sinon exécuter un script avec la session
# de la personne qui l'ouvre.
INLINE_TYPES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".webp": "image/webp", ".gif": "image/gif"}


def _file_response(path: Path) -> FileResponse:
    media = INLINE_TYPES.get(path.suffix.lower())
    if media:
        return FileResponse(path, media_type=media, filename=path.name, content_disposition_type="inline")
    return FileResponse(path, media_type="application/octet-stream", filename=path.name,
                        content_disposition_type="attachment")


# ── Dossiers de classement ───────────────────────────────────────────────
@router.get("/folders")
def folders() -> list[dict]:
    return drive_tree()


def _folder(key: str) -> Path:
    if key not in config.FOLDERS:
        raise services.NotFound("Dossier inconnu")
    return config.FOLDERS[key]


@router.get("/folders/{key}")
def folder_files(key: str) -> dict:
    root = _folder(key)
    files = sorted((p for p in root.rglob("*") if p.is_file() and not p.name.startswith(".")),
                   key=lambda p: p.stat().st_mtime, reverse=True) if root.exists() else []
    return {"key": key, "name": root.name, "path": str(root.relative_to(config.DRIVE_DIR.parent)),
            "files": [{"name": p.name, "path": str(p.relative_to(root)), "folder": str(p.parent.relative_to(root)),
                       "size": p.stat().st_size, "modified": p.stat().st_mtime} for p in files[:300]]}


@router.get("/folders/{key}/file")
def folder_file(key: str, path: str) -> FileResponse:
    root = _folder(key).resolve()
    target = (root / path).resolve()
    if root not in target.parents or not target.is_file():
        raise services.NotFound("Fichier introuvable")
    return _file_response(target)
