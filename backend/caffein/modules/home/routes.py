# SPDX-License-Identifier: AGPL-3.0-or-later
"""Routes de l'Accueil : tableau de bord, actualités, « Mes vues »."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Depends, Request, Response

from ... import ai, config, dashboard, db, services
from ...core import modules as registry
from ...core.deps import client_ip, current_user, require
from ...core.permissions import READ, WRITE, levels_for
from ...jobs import job_module, run_job
from ...utils import today

log = logging.getLogger("caffein.home")

# Tout utilisateur connecté a l'Accueil (au moins en lecture) : voir core/permissions.py
router = APIRouter(prefix="/api", dependencies=[Depends(require("home", READ))])


def kpis_for(levels: dict[str, int]) -> list[dict]:
    """Chiffres clés des modules actifs que l'utilisateur peut consulter, calculés par chaque module."""
    out = []
    for module in registry.ordered():
        if levels.get(module.key, 0) < READ:
            continue
        for kpi in module.kpis:
            try:
                data = kpi.compute() or {}
            except Exception:  # un module en erreur ne doit pas casser l'accueil
                log.exception("Chiffre clé %s.%s indisponible", module.key, kpi.key)
                continue
            out.append({
                "key": f"{module.key}.{kpi.key}", "module": module.key, "label": kpi.label, "unit": kpi.unit,
                "value": data.get("value"), "count": data.get("count"), "foot": kpi.foot, "icon": kpi.icon,
                "path": kpi.path, "alert": bool(kpi.alert and kpi.alert(data)),
            })
    return out


def shortcuts_for(levels: dict[str, int]) -> list[dict]:
    return [{"key": f"{m.key}.{s.key}", "module": m.key, "label": s.label, "path": s.path, "icon": s.icon}
            for m in registry.ordered() for s in m.shortcuts if levels.get(m.key, 0) >= s.level]


@router.get("/home")
def home(user: dict = Depends(current_user)) -> dict:
    levels = levels_for(user)
    accounting = levels.get("accounting", 0) >= READ
    visible_jobs = {name for name in _job_names() if levels.get(job_module(name) or "home", 0) >= READ}
    activity = [a for a in db.fetch_all("""
        SELECT id, job, summary, status, started_at FROM job_runs
        WHERE json_extract(details, '$.notable') = 1 OR status = 'error'
        ORDER BY started_at DESC, id DESC LIMIT 40""") if a["job"] in visible_jobs][:6]
    return {
        "kpis": kpis_for(levels),
        "shortcuts": shortcuts_for(levels),
        "next_deadlines": services.upcoming_deadlines(today())[:3] if accounting else [],
        "inbox_count": len(services.inbox_files()) if accounting else 0,
        "activity": activity,
        "notifications": services.list_notifications(),
    }


def _job_names() -> list[str]:
    from ...jobs import JOBS

    return list(JOBS)


# ── Actualités ───────────────────────────────────────────────────────────
@router.get("/notifications")
def notifications() -> list[dict]:
    return services.list_notifications()


@router.post("/notifications/ingest", dependencies=[Depends(require("home", WRITE))])
def notifications_ingest(payload: dict = Body(...), user: dict = Depends(current_user)) -> dict:
    text = str(payload.get("text", "")).strip()
    if len(text) < 10:
        raise ValueError("Collez le contenu de la newsletter.")
    run = run_job("newsletter_notifications", trigger="manual", actor=user["email"], text=text)
    return {"run": run, "notifications": services.list_notifications()}


# ── Tableau de bord à la demande (« Mes vues ») ──────────────────────────
# Les vues sont propres à chaque utilisateur ; une carte n'apparaît que si son module lui est accessible.
@router.post("/dashboards/compose")
def dashboard_compose(request: Request, payload: dict = Body(...), user: dict = Depends(current_user)) -> dict:
    """Demande en langage naturel + vue actuelle → nouvelle vue, avec ses données (lecture seule)."""
    text = str(payload.get("text", "")).strip()
    if len(text) < 3:
        raise ValueError("Dites ce que vous voulez voir.")
    if len(text) > dashboard.MAX_PROMPT:
        raise ValueError(f"Demande trop longue ({dashboard.MAX_PROMPT} caractères au plus).")
    language = "en" if payload.get("language") == "en" else "fr"
    levels = levels_for(user)
    # Quota d'appels à l'IA par utilisateur (et par adresse IP en démo, où tous partagent le même compte)
    quota_key = f"{user['id']}|{client_ip(request)}" if user.get("is_demo") else str(user["id"])
    allow_ai = config.AI_ENABLED and dashboard.ai_allowed(quota_key)
    result = ai.compose_dashboard(text, payload.get("spec") or {}, today(), language, allow_ai=allow_ai, levels=levels)
    return {"view": dashboard.render(result["spec"], levels), "understood": result["understood"],
            "reply": result.get("reply"), "message": result.get("message"), "composed_by": result["composed_by"]}


@router.post("/dashboards/render")
def dashboard_render(payload: dict = Body(...), user: dict = Depends(current_user)) -> dict:
    """Vue → données, sans IA (vue enregistrée, carte retirée…)."""
    return dashboard.render(payload.get("spec") or {}, levels_for(user))


@router.get("/dashboards")
def dashboard_views(user: dict = Depends(current_user)) -> dict:
    return {"views": dashboard.list_views(user["id"]), "catalog": dashboard.catalog(levels_for(user)), "ai": ai.status()}


@router.post("/dashboards", status_code=201)
def dashboard_create(payload: dict = Body(...), user: dict = Depends(current_user)) -> dict:
    return dashboard.create_view(user["id"], payload)


@router.get("/dashboards/{view_id}")
def dashboard_get(view_id: int, user: dict = Depends(current_user)) -> dict:
    view = dashboard.get_view(user["id"], view_id)
    return {**view, "view": dashboard.render(view["spec"], levels_for(user))}


@router.put("/dashboards/{view_id}")
def dashboard_update(view_id: int, payload: dict = Body(...), user: dict = Depends(current_user)) -> dict:
    return dashboard.update_view(user["id"], view_id, payload)


@router.delete("/dashboards/{view_id}", status_code=204)
def dashboard_delete(view_id: int, user: dict = Depends(current_user)) -> Response:
    dashboard.delete_view(user["id"], view_id)
    return Response(status_code=204)
