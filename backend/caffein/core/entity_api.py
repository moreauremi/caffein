# SPDX-License-Identifier: AGPL-3.0-or-later
"""API générique des entités : /api/data/<module>/<entité>[/<id>[/actions/<action>]].

Lecture : niveau « lecture » sur le module ; création, modification, actions : « écriture » (ou le niveau
de l'action) ; suppression : niveau `delete_level` de l'entité (« gestion » par défaut).
"""

from __future__ import annotations

import csv
import io
import re

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response

from ..utils import today
from . import entities
from . import modules as registry
from .deps import check_access, current_user
from .errors import NotFound
from .permissions import READ, WRITE, level_for

router = APIRouter(prefix="/api/data")
_NUMBER = re.compile(r"^-\d[\d\s.,]*$")


def _entity(module: str, name: str) -> entities.Entity:
    try:
        entity = entities.get(f"{module}.{name}")
    except NotFound:
        raise HTTPException(404, "Entité inconnue") from None
    return entity


def _level(user: dict, entity: entities.Entity, needed: int) -> int:
    check_access(user, entity.module, needed)
    return level_for(user, entity.module)


@router.get("/{module}/{name}")
def list_rows(module: str, name: str, request: Request, q: str | None = Query(None, max_length=100),
              sort: str | None = Query(None, max_length=60), dir: str = Query("asc", pattern="^(asc|desc)$"),
              page: int = Query(1, ge=1, le=100_000), size: int = Query(50, ge=1, le=entities.MAX_PAGE),
              user: dict = Depends(current_user)) -> dict:
    entity = _entity(module, name)
    level = _level(user, entity, READ)
    filters = {k[2:]: v for k, v in request.query_params.items() if k.startswith("f_")}
    return entities.list_rows(entity, level, q=q, filters=filters, sort=sort, direction=dir, page=page, size=size)


@router.get("/{module}/{name}/export")
def export(module: str, name: str, request: Request, q: str | None = Query(None, max_length=100),
           sort: str | None = Query(None, max_length=60), dir: str = Query("asc", pattern="^(asc|desc)$"),
           lang: str = Query("fr", pattern="^(fr|en)$"), user: dict = Depends(current_user)) -> Response:
    """Export tableur (CSV) de la liste, avec la recherche, les filtres et le tri de l'écran.
    Point-virgule et virgule décimale en français (Excel), virgule et point en anglais ; UTF-8 avec BOM."""
    entity = _entity(module, name)
    level = _level(user, entity, READ)
    filters = {k[2:]: v for k, v in request.query_params.items() if k.startswith("f_")}
    headers, rows = entities.export_rows(entity, level, language=lang, q=q, filters=filters, sort=sort, direction=dir)
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";" if lang == "fr" else ",", lineterminator="\r\n")
    writer.writerow(headers)
    writer.writerows([[_safe_cell(v) for v in row] for row in rows])
    filename = f"{entity.module}-{entity.name}-{today().isoformat()}.csv"
    return Response("\ufeff" + buffer.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _safe_cell(value: str) -> str:
    """Une cellule qui commence par = + - @ serait interprétée comme une formule par un tableur : on la neutralise."""
    if value and value[0] in "=+@\t\r" or (value.startswith("-") and not _NUMBER.match(value)):
        return "'" + value
    return value


@router.get("/{module}/{name}/options")
def options(module: str, name: str, q: str | None = Query(None, max_length=100),
            source: str | None = Query(None, alias="for", max_length=120), user: dict = Depends(current_user)) -> list[dict]:
    """Choix d'une référence. Autorisé avec la lecture du module de l'entité, ou depuis le formulaire
    d'une entité (`for=module.entité.champ`) qui y fait référence et que l'utilisateur peut modifier.
    Depuis un formulaire, chaque choix porte aussi les valeurs que le champ recopie (`fill`)."""
    entity = _entity(module, name)
    ref_field, src = None, None
    if source and source.count(".") == 2:
        src_module, src_name, src_field = source.split(".")
        try:
            src = entities.get(f"{src_module}.{src_name}")
        except NotFound:
            src = None
        if src is not None:
            candidates = src.fields + [f for c in src.children for f in c.fields]
            ref_field = next((f for f in candidates if f.name == src_field and f.type == "ref" and f.ref == entity.key), None)
    allowed = registry.is_enabled(entity.module) and level_for(user, entity.module) >= READ
    if not allowed and ref_field is not None:
        check_access(user, src.module, WRITE)
        allowed = registry.is_enabled(entity.module)
    if not allowed:
        check_access(user, entity.module, READ)
    return entities.options(entity, q, fill=ref_field.fill if ref_field is not None else None)


@router.get("/{module}/{name}/{row_id}")
def get_row(module: str, name: str, row_id: int, user: dict = Depends(current_user)) -> dict:
    entity = _entity(module, name)
    return entities.get_row(entity, row_id, _level(user, entity, READ), user)


@router.post("/{module}/{name}/preview")
def preview(module: str, name: str, data: dict = Body(...), row_id: int | None = Query(None, alias="id"),
            user: dict = Depends(current_user)) -> dict:
    """Champs calculés d'une saisie en cours (totaux…), calculés par le serveur sans rien enregistrer."""
    entity = _entity(module, name)
    return entities.preview(entity, data, _level(user, entity, WRITE), row_id)


@router.post("/{module}/{name}", status_code=201)
def create_row(module: str, name: str, data: dict = Body(...), user: dict = Depends(current_user)) -> dict:
    entity = _entity(module, name)
    level = _level(user, entity, WRITE)
    row_id = entities.save_row(entity, data, level)
    return entities.get_row(entity, row_id, level, user)


@router.put("/{module}/{name}/{row_id}")
def update_row(module: str, name: str, row_id: int, data: dict = Body(...), user: dict = Depends(current_user)) -> dict:
    entity = _entity(module, name)
    level = _level(user, entity, WRITE)
    entities.save_row(entity, data, level, row_id)
    return entities.get_row(entity, row_id, level, user)


@router.delete("/{module}/{name}/{row_id}", status_code=204)
def delete_row(module: str, name: str, row_id: int, user: dict = Depends(current_user)) -> Response:
    entity = _entity(module, name)
    _level(user, entity, entity.delete_level)
    entities.delete_row(entity, row_id)
    return Response(status_code=204)


@router.post("/{module}/{name}/{row_id}/actions/{action}")
def run_action(module: str, name: str, row_id: int, action: str, payload: dict = Body(default={}),
               user: dict = Depends(current_user)) -> dict:
    entity = _entity(module, name)
    level = _level(user, entity, READ)
    result = entities.run_action(entity, row_id, action, payload, user, level)
    message = result.get("message") if isinstance(result, dict) else (result if isinstance(result, str) else None)
    return {"row": entities.get_row(entity, row_id, level, user), "message": message}
