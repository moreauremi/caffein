# SPDX-License-Identifier: AGPL-3.0-or-later
"""Routes des Paramètres.

- administrateurs : entreprise, utilisateurs et leurs droits, rôles, modules, réinitialisation ;
- tout utilisateur connecté : automatisations et emails des modules qu'il peut consulter.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from fastapi.responses import HTMLResponse

from ... import ai, auth, config, db, emailer, services
from ...core import modules as registry
from ...core import permissions
from ...core.deps import admin_user, check_access, current_user
from ...core.permissions import READ, WRITE, levels_for
from ...jobs import JOBS, describe_jobs, job_module, list_runs, run_job

router = APIRouter()
admin = APIRouter(prefix="/api", dependencies=[Depends(admin_user)])
connected = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


# ═════════════════════════════════════════════════════════════════════════
# Entreprise
# ═════════════════════════════════════════════════════════════════════════
@admin.put("/profile")
def put_profile(values: dict = Body(...)) -> dict:
    return services.update_profile(values)


@admin.post("/admin/reset")
def admin_reset(payload: dict = Body(default={})) -> dict:
    """Efface les données métier (les comptes, rôles et modules sont conservés), puis recharge la démo ou repart à vide."""
    from ...seed import init_instance, seed

    keep = {k: v for k, v in services.get_profile().items() if k in services.PROFILE_EDITABLE}
    if payload.get("mode") == "demo":
        seed(reset=True)
    else:
        init_instance(keep, reset=True)
    return {"ok": True}


# ═════════════════════════════════════════════════════════════════════════
# Utilisateurs
# ═════════════════════════════════════════════════════════════════════════
def _with_access(user: dict) -> dict:
    levels = levels_for(user)
    return {**user, "levels": levels, "overrides": permissions.user_overrides(user["id"])}


@admin.get("/users")
def users() -> list[dict]:
    return [_with_access(u) for u in auth.list_users()]


@admin.post("/users", status_code=201)
def create_user(payload: dict = Body(...)) -> dict:
    user = auth.create_user(str(payload.get("email", "")), str(payload.get("password", "")),
                            str(payload.get("full_name", "")), str(payload.get("role", "member")),
                            role_id=payload.get("role_id"))
    if isinstance(payload.get("overrides"), dict):
        permissions.set_user_overrides(user["id"], payload["overrides"])
    return _with_access(user)


@admin.put("/users/{user_id}")
def update_user(user_id: int, payload: dict = Body(...), user: dict = Depends(admin_user)) -> dict:
    fields = ("full_name", "email", "role", "role_id", "active")
    updated = auth.update_user(user_id, {k: payload[k] for k in fields if k in payload}, user)
    return _with_access(updated)


@admin.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, user: dict = Depends(admin_user)) -> Response:
    auth.delete_user(user_id, user)
    return Response(status_code=204)


@admin.post("/users/{user_id}/password")
def reset_user_password(user_id: int, payload: dict = Body(...)) -> dict:
    if not auth.get_user(user_id):
        raise services.NotFound("Utilisateur introuvable")
    auth.set_password(user_id, str(payload.get("password", "")))
    return {"ok": True}


@admin.get("/users/{user_id}/permissions")
def user_permissions(user_id: int) -> dict:
    user = auth.get_user(user_id)
    if not user:
        raise services.NotFound("Utilisateur introuvable")
    role = permissions.get_role(user["role_id"]) if user.get("role_id") else None
    return {"user": _with_access(user), "role": role}


@admin.put("/users/{user_id}/permissions")
def set_user_permissions(user_id: int, payload: dict = Body(...)) -> dict:
    """Dérogations par module : {"overrides": {"hr": 0, "sales": 3, "stock": null}} (null : suivre le rôle)."""
    if not auth.get_user(user_id):
        raise services.NotFound("Utilisateur introuvable")
    permissions.set_user_overrides(user_id, payload.get("overrides"))
    return user_permissions(user_id)


# ═════════════════════════════════════════════════════════════════════════
# Rôles et droits
# ═════════════════════════════════════════════════════════════════════════
def _matrix_modules() -> list[dict]:
    """Modules qui se règlent par rôle (l'Accueil et les Paramètres sont toujours là)."""
    return [{"key": m["key"], "label": m["label"], "icon": m["icon"], "enabled": m["enabled"]}
            for m in registry.describe() if not m["core"]]


@admin.get("/settings/roles")
def roles() -> dict:
    return {"roles": permissions.list_roles(), "modules": _matrix_modules()}


@admin.post("/settings/roles", status_code=201)
def create_role(payload: dict = Body(...)) -> dict:
    return permissions.create_role(payload)


@admin.put("/settings/roles/{role_id}")
def update_role(role_id: int, payload: dict = Body(...)) -> dict:
    return permissions.update_role(role_id, payload)


@admin.delete("/settings/roles/{role_id}", status_code=204)
def delete_role(role_id: int) -> Response:
    permissions.delete_role(role_id)
    return Response(status_code=204)


# ═════════════════════════════════════════════════════════════════════════
# Modules
# ═════════════════════════════════════════════════════════════════════════
@admin.get("/settings/modules")
def modules() -> list[dict]:
    return registry.describe()


@admin.put("/settings/modules/{key}")
def toggle_module(key: str, payload: dict = Body(...)) -> list[dict]:
    if not isinstance(payload.get("enabled"), bool):
        raise ValueError("Indiquez enabled : true ou false.")
    registry.set_enabled(key, payload["enabled"])
    return registry.describe()


# ═════════════════════════════════════════════════════════════════════════
# Automatisations et emails (selon les modules accessibles)
# ═════════════════════════════════════════════════════════════════════════
# Type d'email → module dont il dépend
EMAIL_MODULES = {"invoice": "sales", "quote": "sales", "reminder": "sales", "notification": "sales", "alert": "accounting"}


def _visible_jobs(user: dict) -> set[str]:
    return {j["name"] for j in describe_jobs(levels_for(user))}


@connected.get("/automations")
def automations(user: dict = Depends(current_user)) -> dict:
    levels = levels_for(user)
    accounting = levels.get("accounting", 0) >= READ
    return {"jobs": describe_jobs(levels), "ai": ai.status(), "email": emailer.status(), "scheduler": config.SCHEDULER_ENABLED,
            "inbox_count": len(services.inbox_files()) if accounting else 0, "imap": bool(config.IMAP_HOST)}


@connected.get("/automations/runs")
def automation_runs(job: str | None = None, limit: int = Query(60, ge=1, le=300), user: dict = Depends(current_user)) -> list[dict]:
    return list_runs(limit, job, jobs=_visible_jobs(user))


@connected.post("/automations/{name}/run")
def automation_run(name: str, payload: dict = Body(default={}), user: dict = Depends(current_user)) -> dict:
    spec = JOBS.get(name)
    if spec is None or name not in _visible_jobs(user):
        raise services.NotFound("Script inconnu")
    check_access(user, job_module(name) or "home", WRITE)
    if not spec.manual:
        raise services.Conflict("Ce script se déclenche depuis une facture (bouton Émettre / Envoyer).")
    kwargs = {"text": payload["text"]} if name == "newsletter_notifications" and payload.get("text") else {}
    return run_job(name, trigger="manual", actor=user["email"], **kwargs)


def _email_kinds(user: dict) -> set[str] | None:
    """Types d'emails visibles (None : tous). Un type sans module (prise en main…) relève de l'Accueil."""
    if user.get("role") == "admin":
        return None
    levels = levels_for(user)
    known = {kind for kind, module in EMAIL_MODULES.items() if levels.get(module, 0) >= READ}
    return known | {"*other*"}


def _email_visible(kind: str, kinds: set[str] | None) -> bool:
    return kinds is None or kind in kinds or (kind not in EMAIL_MODULES and "*other*" in kinds)


@connected.get("/emails")
def emails(kind: str | None = None, limit: int = Query(100, ge=1, le=500), user: dict = Depends(current_user)) -> list[dict]:
    where, params = [], []
    if kind:
        where.append("kind = ?")
        params.append(kind)
    kinds = _email_kinds(user)
    if kinds is not None:
        allowed = sorted(k for k in kinds if k != "*other*") or [""]
        every = sorted(EMAIL_MODULES)
        where.append(f"(kind IN ({', '.join('?' for _ in allowed)}) OR kind NOT IN ({', '.join('?' for _ in every)}))")
        params += allowed + every
    sql = "SELECT id, kind, to_email, from_email, subject, status, error, attachment_name, invoice_id, meta, created_at FROM emails"
    if where:
        sql += " WHERE " + " AND ".join(where)
    rows = db.fetch_all(sql + " ORDER BY created_at DESC, id DESC LIMIT ?", (*params, limit))
    for row in rows:
        row["meta"] = db.loads(row["meta"], {})
    return rows


@connected.get("/emails/{email_id}/html", response_class=HTMLResponse)
def email_html(email_id: int, user: dict = Depends(current_user)) -> HTMLResponse:
    row = db.fetch_one("SELECT kind, html FROM emails WHERE id = ?", (email_id,))
    if not row or not _email_visible(row["kind"], _email_kinds(user)):
        raise HTTPException(404, "Email introuvable")
    return HTMLResponse(row["html"], headers={
        "Content-Security-Policy": "default-src 'none'; img-src * data:; style-src 'unsafe-inline'",
        "X-Frame-Options": "SAMEORIGIN",
    })


router.include_router(admin)
router.include_router(connected)
