# SPDX-License-Identifier: AGPL-3.0-or-later
"""API HTTP de Caffein.

Toutes les routes sont sous /api ; l'interface React buildée (frontend/dist) est servie par le même serveur.
- public : santé, assistant d'installation, connexion, page publique d'une facture ;
- socle (utilisateur connecté) : compte, configuration, description de l'espace (/api/meta) ;
- moteur de données : /api/data/<module>/<entité> (core/entity_api.py) ;
- chaque module apporte ses routes (caffein/modules/<clé>/routes.py), contrôlées par les droits du module :
  un module désactivé répond 404, un niveau insuffisant 403. Voir docs/modules.md.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .. import __version__, ai, auth, config, db, emailer, services
from ..core import entity_api, meta
from ..core import modules as registry
from ..core.deps import SAFE_METHODS, current_user, open_session
from ..core.errors import Conflict, Forbidden, NotFound
from ..jobs import run_job
from ..modules.sales.routes import pdf_response
from ..utils import today

log = logging.getLogger("caffein.api")
SPA_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
           "font-src 'self' data:; connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'self'; "
           "form-action 'self'; frame-ancestors 'self'")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    auth.purge_expired_sessions()
    if config.DEMO_MODE:
        from ..seed import is_empty, seed, seed_demo_team

        if is_empty():
            seed()
            log.info("Mode démo : données de démonstration créées.")
        auth.ensure_demo_user()
        seed_demo_team()
    elif auth.count_users() == 0:
        log.info("Aucun compte : ouvrez %s pour lancer l'assistant d'installation.", config.APP_URL)
    if config.SCHEDULER_ENABLED:
        from ..scheduler import start_background, stop_background

        start_background()
        yield
        stop_background()
    else:
        yield


app = FastAPI(title="Caffein API", version=__version__, lifespan=lifespan,
              docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")


# ── Sécurité transversale ────────────────────────────────────────────────
def _same_origin(origin: str, request: Request) -> bool:
    netloc = urlparse(origin).netloc
    return netloc in {request.headers.get("host", ""), urlparse(config.APP_URL).netloc}


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    # Protection CSRF : une requête d'écriture venant d'un autre site est refusée
    if request.method not in SAFE_METHODS and request.url.path.startswith("/api/"):
        origin = request.headers.get("origin")
        if origin and not _same_origin(origin, request):
            return JSONResponse({"detail": "Origine de la requête refusée."}, status_code=403)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    return response


@app.exception_handler(NotFound)
async def _not_found(_req: Request, exc: NotFound):
    return JSONResponse({"detail": str(exc)}, status_code=404)


@app.exception_handler(LookupError)
async def _lookup(_req: Request, exc: LookupError):
    return JSONResponse({"detail": str(exc)}, status_code=404)


@app.exception_handler(Conflict)
async def _conflict(_req: Request, exc: Conflict):
    return JSONResponse({"detail": str(exc)}, status_code=409)


@app.exception_handler(Forbidden)
async def _forbidden(_req: Request, exc: Forbidden):
    return JSONResponse({"detail": str(exc)}, status_code=403)


@app.exception_handler(ValueError)
async def _bad_request(_req: Request, exc: ValueError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(OverflowError)
async def _overflow(_req: Request, _exc: OverflowError):
    # identifiant ou nombre hors de la plage des entiers SQLite (2^63)
    return JSONResponse({"detail": "Nombre hors limites."}, status_code=400)


@app.exception_handler(auth.AuthError)
async def _auth_error(_req: Request, exc: auth.AuthError):
    return JSONResponse({"detail": str(exc)}, status_code=401)


public = APIRouter(prefix="/api")
core = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


@public.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__, "schema": db.schema_version()}


@public.get("/setup/status")
def setup_status() -> dict:
    needs_setup = auth.count_users() == 0
    # L'assistant propose les modules à activer
    modules = [{k: m[k] for k in ("key", "label", "description", "icon", "core", "depends", "default_enabled")}
               for m in registry.describe()] if needs_setup else []
    return {"needs_setup": needs_setup, "demo": config.DEMO_MODE, "version": __version__, "modules": modules}


ORGANIZATION_FIELDS = ("company", "full_name", "email", "phone", "address", "zip_code", "city", "siret",
                       "activity", "declaration_frequency", "vat_exempt", "default_vat_rate", "legal_mention")


@public.post("/setup", status_code=201)
def setup(request: Request, response: Response, payload: dict = Body(...)) -> dict:
    """Assistant d'installation : n'est utilisable que tant qu'aucun compte n'existe."""
    if auth.count_users() > 0:
        raise Conflict("Caffein est déjà installé.")
    admin_data = payload.get("admin") or {}
    auth.check_password_strength(admin_data.get("password", ""))
    organization = {k: v for k, v in (payload.get("organization") or {}).items() if k in ORGANIZATION_FIELDS}
    if not organization.get("company") and not organization.get("full_name"):
        raise ValueError("Indiquez le nom de votre entreprise.")
    organization.setdefault("full_name", admin_data.get("full_name", ""))
    organization.setdefault("email", admin_data.get("email", ""))

    from ..seed import init_instance, seed

    if payload.get("demo_data"):
        seed(reset=True)  # la démonstration active tous les modules
        services.update_profile(organization)
    else:
        init_instance(organization, reset=True)
        if payload.get("modules") is not None:
            registry.set_selection(payload["modules"])
    user = auth.create_user(admin_data.get("email", ""), admin_data["password"], admin_data.get("full_name", ""), "admin")
    run_job("setup_drive", trigger="event", actor=user["email"])
    open_session(response, request, user)
    return {"user": user}


@public.post("/auth/login")
def login(request: Request, response: Response, payload: dict = Body(...)) -> dict:
    ip = request.client.host if request.client else ""
    user = auth.authenticate(str(payload.get("email", "")), str(payload.get("password", "")), ip)
    open_session(response, request, user)
    return {"user": user}


@public.post("/auth/demo")
def demo_login(request: Request, response: Response) -> dict:
    if not config.DEMO_MODE:
        raise NotFound("Le mode démo n'est pas activé sur cette instance.")
    user = auth.ensure_demo_user()
    open_session(response, request, user)
    return {"user": user}


@public.post("/auth/logout", status_code=204)
def logout(request: Request) -> Response:
    auth.delete_session(request.cookies.get(auth.COOKIE_NAME))
    response = Response(status_code=204)
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return response


# ── Page publique d'une facture (lien des emails, sans connexion) ────────
# Toujours disponible, même si le module Ventes est désactivé : le client garde l'accès à sa facture.
def _public_payload(inv: dict) -> dict:
    profile = services.get_profile()
    keys = ("kind", "number", "title", "subtotal", "vat_amount", "total", "vat_exempt", "vat_rate",
            "issued_at", "due_date", "display_status", "paid_at")
    invoice = {k: inv.get(k) for k in keys}
    invoice["items"] = [{k: line[k] for k in ("description", "quantity", "unit_price", "amount")} for line in inv["items"]]
    return {
        "invoice": invoice,
        "client": {"name": (inv["client"] or {}).get("name", "")},
        "issuer": {k: profile.get(k) for k in ("company", "full_name", "address", "zip_code", "city", "email", "phone",
                                               "siret", "iban", "bic")},
    }


@public.get("/public/invoices/{token}")
def public_invoice(token: str) -> dict:
    return _public_payload(services.get_invoice_by_token(token))


@public.get("/public/invoices/{token}/pdf")
def public_invoice_pdf(token: str, download: bool = False) -> Response:
    inv = services.get_invoice_by_token(token)
    content, filename = services.render_pdf_bytes(inv["id"])
    return pdf_response(content, filename, download)


# ── Socle : compte, configuration, description de l'espace ───────────────
@core.get("/auth/me")
def me(user: dict = Depends(current_user)) -> dict:
    return user


@core.put("/auth/me")
def update_me(payload: dict = Body(...), user: dict = Depends(current_user)) -> dict:
    return auth.update_user(user["id"], {k: payload[k] for k in ("full_name", "email") if k in payload}, user)


@core.post("/auth/password")
def change_password(request: Request, response: Response, payload: dict = Body(...), user: dict = Depends(current_user)) -> dict:
    row = auth.get_user_by_email(user["email"])
    if not auth.verify_password(str(payload.get("current_password", "")), row["password_hash"]):
        raise ValueError("Mot de passe actuel incorrect.")
    auth.set_password(user["id"], str(payload.get("new_password", "")))  # révoque toutes les sessions…
    open_session(response, request, user)                                 # …puis rouvre celle-ci
    return {"ok": True}


@core.get("/config")
def get_config() -> dict:
    return {"version": __version__, "today": today().isoformat(), "ai": ai.status(), "email": emailer.status(),
            "scheduler": config.SCHEDULER_ENABLED, "app_url": config.APP_URL, "demo": config.DEMO_MODE,
            "license": config.LICENSE, "source_url": config.SOURCE_URL, "schema": db.schema_version()}


@core.get("/profile")
def get_profile() -> dict:
    return services.get_profile()


@core.get("/meta")
def get_meta(user: dict = Depends(current_user)) -> dict:
    """Modules, pages, entités et droits de l'utilisateur : l'interface construit sa navigation avec."""
    return meta.build(user)


app.include_router(public)
app.include_router(core)
app.include_router(entity_api.router)
for _module in registry.ordered():
    if _module.router is not None:
        app.include_router(_module.router)


# ── Interface React buildée ──────────────────────────────────────────────
@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404, "Route API inconnue")
    dist = config.FRONTEND_DIST
    index = dist / "index.html"
    if not index.exists():
        return HTMLResponse(
            "<h1>Caffein</h1><p>L'interface n'est pas buildée : lancez <code>cd frontend && npm ci && npm run build</code>.</p>"
            "<p>API : <a href='/api/docs'>/api/docs</a></p>", status_code=503)
    candidate = (dist / full_path).resolve()
    if full_path and dist in candidate.parents and candidate.is_file():
        cache = "public, max-age=31536000, immutable" if full_path.startswith("assets/") else "no-cache"
        return FileResponse(candidate, headers={"Cache-Control": cache})
    return FileResponse(index, headers={"Cache-Control": "no-cache", "Content-Security-Policy": SPA_CSP})
