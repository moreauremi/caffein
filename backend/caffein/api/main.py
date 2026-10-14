# SPDX-License-Identifier: AGPL-3.0-or-later
"""API HTTP de Caffein (remplace les webhooks n8n et les appels directs à Supabase).

Toutes les routes sont sous /api ; l'interface React buildée (frontend/dist) est
servie par le même serveur. Trois niveaux d'accès :
- public : santé, assistant d'installation, connexion, page publique d'une facture ;
- connecté (`api`) : toute l'activité (factures, documents, scripts…) ;
- administrateur (`admin`) : paramètres de l'entreprise, utilisateurs, réinitialisation.
"""

from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Body, Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from .. import __version__, ai, auth, config, dashboard, db, emailer, services
from ..jobs import JOBS, describe_jobs, list_runs, run_job
from ..jobs.setup_drive import tree as drive_tree
from ..utils import today, unique_path

log = logging.getLogger("caffein.api")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
SPA_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
           "font-src 'self' data:; connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'self'; "
           "form-action 'self'; frame-ancestors 'self'")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    auth.purge_expired_sessions()
    if config.DEMO_MODE:
        from ..seed import is_empty, seed

        if is_empty():
            seed()
            log.info("Mode démo : données de démonstration créées.")
        auth.ensure_demo_user()
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


@app.exception_handler(services.NotFound)
async def _not_found(_req: Request, exc: services.NotFound):
    return JSONResponse({"detail": str(exc)}, status_code=404)


@app.exception_handler(LookupError)
async def _lookup(_req: Request, exc: LookupError):
    return JSONResponse({"detail": str(exc)}, status_code=404)


@app.exception_handler(services.Conflict)
async def _conflict(_req: Request, exc: services.Conflict):
    return JSONResponse({"detail": str(exc)}, status_code=409)


@app.exception_handler(ValueError)
async def _bad_request(_req: Request, exc: ValueError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(auth.AuthError)
async def _auth_error(_req: Request, exc: auth.AuthError):
    return JSONResponse({"detail": str(exc)}, status_code=401)


# ── Authentification ─────────────────────────────────────────────────────
def current_user(request: Request) -> dict:
    user = auth.user_from_token(request.cookies.get(auth.COOKIE_NAME))
    if not user:
        raise HTTPException(401, "Connexion requise.")
    return user


def admin_user(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Action réservée aux administrateurs.")
    return user


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _open_session(response: Response, request: Request, user: dict) -> None:
    token = auth.create_session(user["id"], _client_ip(request), request.headers.get("user-agent", ""))
    response.set_cookie(auth.COOKIE_NAME, token, max_age=config.SESSION_DAYS * 86400, httponly=True,
                        samesite="lax", secure=config.SECURE_COOKIES, path="/")


public = APIRouter(prefix="/api")
api = APIRouter(prefix="/api", dependencies=[Depends(current_user)])
admin = APIRouter(prefix="/api", dependencies=[Depends(admin_user)])


@public.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__, "schema": db.schema_version()}


@public.get("/setup/status")
def setup_status() -> dict:
    return {"needs_setup": auth.count_users() == 0, "demo": config.DEMO_MODE, "version": __version__}


ORGANIZATION_FIELDS = ("company", "full_name", "email", "phone", "address", "zip_code", "city", "siret",
                       "activity", "declaration_frequency", "vat_exempt", "default_vat_rate", "legal_mention")


@public.post("/setup", status_code=201)
def setup(request: Request, response: Response, payload: dict = Body(...)) -> dict:
    """Assistant d'installation : n'est utilisable que tant qu'aucun compte n'existe."""
    if auth.count_users() > 0:
        raise services.Conflict("Caffein est déjà installé.")
    admin_data = payload.get("admin") or {}
    auth.check_password_strength(admin_data.get("password", ""))
    organization = {k: v for k, v in (payload.get("organization") or {}).items() if k in ORGANIZATION_FIELDS}
    if not organization.get("company") and not organization.get("full_name"):
        raise ValueError("Indiquez le nom de votre entreprise.")
    organization.setdefault("full_name", admin_data.get("full_name", ""))
    organization.setdefault("email", admin_data.get("email", ""))

    from ..seed import init_instance, seed

    if payload.get("demo_data"):
        seed(reset=True)
        services.update_profile(organization)
    else:
        init_instance(organization, reset=True)
    user = auth.create_user(admin_data.get("email", ""), admin_data["password"], admin_data.get("full_name", ""), "admin")
    run_job("setup_drive", trigger="event", actor=user["email"])
    _open_session(response, request, user)
    return {"user": user}


@public.post("/auth/login")
def login(request: Request, response: Response, payload: dict = Body(...)) -> dict:
    user = auth.authenticate(str(payload.get("email", "")), str(payload.get("password", "")), _client_ip(request))
    _open_session(response, request, user)
    return {"user": user}


@public.post("/auth/demo")
def demo_login(request: Request, response: Response) -> dict:
    if not config.DEMO_MODE:
        raise services.NotFound("Le mode démo n'est pas activé sur cette instance.")
    user = auth.ensure_demo_user()
    _open_session(response, request, user)
    return {"user": user}


@public.post("/auth/logout", status_code=204)
def logout(request: Request) -> Response:
    auth.delete_session(request.cookies.get(auth.COOKIE_NAME))
    response = Response(status_code=204)
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return response


@api.get("/auth/me")
def me(user: dict = Depends(current_user)) -> dict:
    return user


@api.put("/auth/me")
def update_me(payload: dict = Body(...), user: dict = Depends(current_user)) -> dict:
    return auth.update_user(user["id"], {k: payload[k] for k in ("full_name", "email") if k in payload}, user)


@api.post("/auth/password")
def change_password(request: Request, response: Response, payload: dict = Body(...), user: dict = Depends(current_user)) -> dict:
    row = auth.get_user_by_email(user["email"])
    if not auth.verify_password(str(payload.get("current_password", "")), row["password_hash"]):
        raise ValueError("Mot de passe actuel incorrect.")
    auth.set_password(user["id"], str(payload.get("new_password", "")))  # révoque toutes les sessions…
    _open_session(response, request, user)                                # …puis rouvre celle-ci
    return {"ok": True}


# ── Utilisateurs (administrateurs) ───────────────────────────────────────
@admin.get("/users")
def users() -> list[dict]:
    return auth.list_users()


@admin.post("/users", status_code=201)
def create_user(payload: dict = Body(...)) -> dict:
    return auth.create_user(str(payload.get("email", "")), str(payload.get("password", "")),
                            str(payload.get("full_name", "")), str(payload.get("role", "member")))


@admin.put("/users/{user_id}")
def update_user(user_id: int, payload: dict = Body(...), user: dict = Depends(admin_user)) -> dict:
    return auth.update_user(user_id, {k: payload[k] for k in ("full_name", "email", "role", "active") if k in payload}, user)


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


# ── Général ──────────────────────────────────────────────────────────────
@api.get("/config")
def get_config() -> dict:
    return {"version": __version__, "today": today().isoformat(), "ai": ai.status(), "email": emailer.status(),
            "scheduler": config.SCHEDULER_ENABLED, "app_url": config.APP_URL, "demo": config.DEMO_MODE,
            "license": config.LICENSE, "source_url": config.SOURCE_URL, "schema": db.schema_version()}


@api.get("/profile")
def get_profile() -> dict:
    return services.get_profile()


@admin.put("/profile")
def put_profile(values: dict = Body(...)) -> dict:
    return services.update_profile(values)


@api.get("/home")
def home() -> dict:
    return services.home_dashboard()


@api.get("/tva")
def tva(period: str = Query("month", pattern="^(month|quarter|year)$")) -> dict:
    return services.tva_dashboard(period)


@api.get("/urssaf")
def urssaf(year: int | None = None) -> dict:
    return services.urssaf_dashboard(year)


@api.post("/urssaf/declarations")
def urssaf_declare(payload: dict = Body(...)) -> dict:
    key = str(payload.get("period_key", ""))
    if not re.fullmatch(r"\d{4}-(\d{2}|T[1-4])", key):
        raise ValueError("Période invalide")
    services.set_declared(key, bool(payload.get("declared", True)))
    return services.urssaf_dashboard(int(key[:4]))


@admin.post("/admin/reset")
def admin_reset(payload: dict = Body(default={})) -> dict:
    """Efface les données métier (les comptes sont conservés), puis recharge la démo ou repart à vide."""
    from ..seed import init_instance, seed

    keep = {k: v for k, v in services.get_profile().items() if k in services.PROFILE_EDITABLE}
    if payload.get("mode") == "demo":
        seed(reset=True)
    else:
        init_instance(keep, reset=True)
    return {"ok": True}


# ── Clients ──────────────────────────────────────────────────────────────
@api.get("/clients")
def clients() -> list[dict]:
    return services.list_clients()


@api.post("/clients", status_code=201)
def create_client(data: dict = Body(...)) -> dict:
    return services.create_client(data)


@api.put("/clients/{client_id}")
def update_client(client_id: int, data: dict = Body(...)) -> dict:
    return services.update_client(client_id, data)


@api.delete("/clients/{client_id}", status_code=204)
def delete_client(client_id: int) -> Response:
    services.delete_client(client_id)
    return Response(status_code=204)


# ── Factures & devis ─────────────────────────────────────────────────────
@api.get("/invoices")
def invoices(kind: str | None = Query(None, pattern="^(invoice|quote)$")) -> list[dict]:
    return services.list_invoices(kind)


@api.get("/invoices/summary")
def invoices_summary() -> dict:
    return services.invoice_summary()


@api.post("/invoices", status_code=201)
def create_invoice(data: dict = Body(...)) -> dict:
    return services.create_invoice(data)


@api.post("/invoices/assistant", status_code=201)
def invoice_assistant(payload: dict = Body(...)) -> dict:
    """Langage naturel → brouillon (« Mission logo pour Jean Martin, 800 €, livraison le 15 »)."""
    text = str(payload.get("text", "")).strip()
    if len(text) < 4:
        raise ValueError("Décrivez la prestation à facturer.")
    kind_hint = payload.get("kind") if payload.get("kind") in ("invoice", "quote") else None
    parsed = ai.parse_invoice_request(text, services.list_clients(), today(), kind_hint)
    profile = services.get_profile()

    client, created_client = None, False
    if parsed.get("existing_client_id"):
        client = services.get_client(int(parsed["existing_client_id"]))
    if client is None and parsed.get("client_name"):
        before = len(services.list_clients())
        client = services.find_or_create_client(parsed["client_name"], parsed.get("client_contact", ""), parsed.get("client_email"))
        created_client = len(services.list_clients()) > before

    items = parsed["items"]
    if parsed.get("amounts_include_vat") and not profile["vat_exempt"]:
        items = [{**it, "unit_price": round(float(it["unit_price"]) / (1 + profile["default_vat_rate"]), 2)} for it in items]
    data: dict[str, Any] = {
        "kind": parsed["kind"], "client_id": client["id"] if client else None, "title": parsed.get("title", ""),
        "items": items, "delivery_date": parsed.get("delivery_date"), "notes": parsed.get("notes", ""), "source_text": text,
    }
    if parsed.get("due_in_days"):
        data["due_date"] = ai.due_date_from(today(), parsed["due_in_days"], profile["payment_terms_days"]).isoformat()
    invoice = services.create_invoice(data)
    return {"invoice": invoice, "parsed_by": parsed.get("parsed_by"), "created_client": created_client}


@api.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: int) -> dict:
    return services.get_invoice(invoice_id)


@api.put("/invoices/{invoice_id}")
def update_invoice(invoice_id: int, data: dict = Body(...)) -> dict:
    return services.update_invoice(invoice_id, data)


@api.delete("/invoices/{invoice_id}", status_code=204)
def delete_invoice(invoice_id: int) -> Response:
    services.delete_invoice(invoice_id)
    return Response(status_code=204)


@api.post("/invoices/{invoice_id}/finalize")
def finalize_invoice(invoice_id: int) -> dict:
    return services.finalize_invoice(invoice_id)


@api.post("/invoices/{invoice_id}/send")
def send_invoice(invoice_id: int, payload: dict = Body(default={}), user: dict = Depends(current_user)) -> dict:
    inv = services.get_invoice(invoice_id)
    recipient = (payload.get("recipient_email") or (inv["client"] or {}).get("email") or "").strip()
    if not recipient:
        # vérifié avant d'émettre : un brouillon ne doit pas recevoir de numéro si l'envoi est impossible
        raise ValueError("Ajoutez une adresse email au client avant l'envoi (onglet Clients).")
    if inv["status"] == "draft":
        services.finalize_invoice(invoice_id)
    run = run_job("send_invoice", trigger="manual", actor=user["email"], invoice_id=invoice_id,
                  recipient_email=payload.get("recipient_email"))
    return {"run": run, "invoice": services.get_invoice(invoice_id)}


@api.post("/invoices/{invoice_id}/paid")
def invoice_paid(invoice_id: int, payload: dict = Body(default={})) -> dict:
    return services.mark_paid(invoice_id, payload.get("paid_at"))


@api.post("/invoices/{invoice_id}/cancel")
def invoice_cancel(invoice_id: int) -> dict:
    return services.cancel_invoice(invoice_id)


@api.post("/invoices/{invoice_id}/remind")
def invoice_remind(invoice_id: int, user: dict = Depends(current_user)) -> dict:
    run = run_job("auto_reminders", trigger="manual", actor=user["email"], invoice_id=invoice_id, force=True)
    return {"run": run, "invoice": services.get_invoice(invoice_id)}


@api.post("/invoices/{invoice_id}/quote-status")
def quote_status(invoice_id: int, payload: dict = Body(...)) -> dict:
    return services.set_quote_status(invoice_id, str(payload.get("status")))


@api.post("/invoices/{invoice_id}/convert", status_code=201)
def quote_convert(invoice_id: int) -> dict:
    return services.convert_quote(invoice_id)


def _pdf_response(content: bytes, filename: str, download: bool) -> Response:
    disposition = "attachment" if download else "inline"
    safe = re.sub(r"[^\w.-]", "_", filename)
    return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'{disposition}; filename="{safe}"'})


@api.get("/invoices/{invoice_id}/pdf")
def invoice_pdf(invoice_id: int, download: bool = False) -> Response:
    content, filename = services.render_pdf_bytes(invoice_id)
    return _pdf_response(content, filename, download)


# ── Page publique d'une facture (lien des emails, sans connexion) ────────
def _public_payload(inv: dict) -> dict:
    profile = services.get_profile()
    keys = ("kind", "number", "title", "items", "subtotal", "vat_amount", "total", "vat_exempt", "vat_rate",
            "issued_at", "due_date", "display_status", "paid_at")
    return {
        "invoice": {k: inv.get(k) for k in keys},
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
    return _pdf_response(content, filename, download)


# ── Documents ────────────────────────────────────────────────────────────
@api.get("/documents")
def documents() -> list[dict]:
    return services.list_documents()


@api.post("/documents/upload")
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


@api.put("/documents/{doc_id}")
def update_document(doc_id: int, data: dict = Body(...)) -> dict:
    return services.update_document(doc_id, data)


@api.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: int) -> Response:
    services.delete_document(doc_id)
    return Response(status_code=204)


@api.get("/documents/{doc_id}/file")
def document_file(doc_id: int) -> FileResponse:
    doc = services.get_document(doc_id)
    if not doc["has_file"]:
        raise services.NotFound("Fichier introuvable")
    return FileResponse(doc["file_path"], filename=Path(doc["file_path"]).name, content_disposition_type="inline")


# ── Dossiers de classement ───────────────────────────────────────────────
@api.get("/folders")
def folders() -> list[dict]:
    return drive_tree()


def _folder(key: str) -> Path:
    if key not in config.FOLDERS:
        raise services.NotFound("Dossier inconnu")
    return config.FOLDERS[key]


@api.get("/folders/{key}")
def folder_files(key: str) -> dict:
    root = _folder(key)
    files = sorted((p for p in root.rglob("*") if p.is_file() and not p.name.startswith(".")),
                   key=lambda p: p.stat().st_mtime, reverse=True) if root.exists() else []
    return {"key": key, "name": root.name, "path": str(root.relative_to(config.DRIVE_DIR.parent)),
            "files": [{"name": p.name, "path": str(p.relative_to(root)), "folder": str(p.parent.relative_to(root)),
                       "size": p.stat().st_size, "modified": p.stat().st_mtime} for p in files[:300]]}


@api.get("/folders/{key}/file")
def folder_file(key: str, path: str) -> FileResponse:
    root = _folder(key).resolve()
    target = (root / path).resolve()
    if root not in target.parents or not target.is_file():
        raise services.NotFound("Fichier introuvable")
    return FileResponse(target, filename=target.name, content_disposition_type="inline")


# ── Actualités ───────────────────────────────────────────────────────────
@api.get("/notifications")
def notifications() -> list[dict]:
    return services.list_notifications()


@api.post("/notifications/ingest")
def notifications_ingest(payload: dict = Body(...), user: dict = Depends(current_user)) -> dict:
    text = str(payload.get("text", "")).strip()
    if len(text) < 10:
        raise ValueError("Collez le contenu de la newsletter.")
    run = run_job("newsletter_notifications", trigger="manual", actor=user["email"], text=text)
    return {"run": run, "notifications": services.list_notifications()}


# ── Tableau de bord à la demande (« Mes vues ») ──────────────────────────
@api.post("/dashboards/compose")
def dashboard_compose(payload: dict = Body(...)) -> dict:
    """Demande en langage naturel + vue actuelle → nouvelle vue, avec ses données (lecture seule)."""
    text = str(payload.get("text", "")).strip()
    if len(text) < 3:
        raise ValueError("Dites ce que vous voulez voir.")
    if len(text) > dashboard.MAX_PROMPT:
        raise ValueError(f"Demande trop longue ({dashboard.MAX_PROMPT} caractères au plus).")
    language = "en" if payload.get("language") == "en" else "fr"
    result = ai.compose_dashboard(text, payload.get("spec") or {}, today(), language)
    return {"view": dashboard.render(result["spec"]), "understood": result["understood"], "reply": result.get("reply"),
            "message": result.get("message"), "composed_by": result["composed_by"]}


@api.post("/dashboards/render")
def dashboard_render(payload: dict = Body(...)) -> dict:
    """Vue → données, sans IA (vue enregistrée, carte retirée…)."""
    return dashboard.render(payload.get("spec") or {})


@api.get("/dashboards")
def dashboard_views(user: dict = Depends(current_user)) -> dict:
    return {"views": dashboard.list_views(user["id"]), "catalog": dashboard.catalog(), "ai": ai.status()}


@api.post("/dashboards", status_code=201)
def dashboard_create(payload: dict = Body(...), user: dict = Depends(current_user)) -> dict:
    return dashboard.create_view(user["id"], payload)


@api.get("/dashboards/{view_id}")
def dashboard_get(view_id: int, user: dict = Depends(current_user)) -> dict:
    view = dashboard.get_view(user["id"], view_id)
    return {**view, "view": dashboard.render(view["spec"])}


@api.put("/dashboards/{view_id}")
def dashboard_update(view_id: int, payload: dict = Body(...), user: dict = Depends(current_user)) -> dict:
    return dashboard.update_view(user["id"], view_id, payload)


@api.delete("/dashboards/{view_id}", status_code=204)
def dashboard_delete(view_id: int, user: dict = Depends(current_user)) -> Response:
    dashboard.delete_view(user["id"], view_id)
    return Response(status_code=204)


# ── Automatisations & emails ─────────────────────────────────────────────
@api.get("/automations")
def automations() -> dict:
    return {"jobs": describe_jobs(), "ai": ai.status(), "email": emailer.status(), "scheduler": config.SCHEDULER_ENABLED,
            "inbox_count": len(services.inbox_files()), "imap": bool(config.IMAP_HOST)}


@api.get("/automations/runs")
def automation_runs(job: str | None = None, limit: int = Query(60, le=300)) -> list[dict]:
    return list_runs(limit, job)


@api.post("/automations/{name}/run")
def automation_run(name: str, payload: dict = Body(default={}), user: dict = Depends(current_user)) -> dict:
    spec = JOBS.get(name)
    if spec is None:
        raise services.NotFound("Script inconnu")
    if not spec.manual:
        raise services.Conflict("Ce script se déclenche depuis une facture (bouton Émettre / Envoyer).")
    kwargs = {"text": payload["text"]} if name == "newsletter_notifications" and payload.get("text") else {}
    return run_job(name, trigger="manual", actor=user["email"], **kwargs)


@api.get("/emails")
def emails(kind: str | None = None, limit: int = Query(100, le=500)) -> list[dict]:
    sql = "SELECT id, kind, to_email, from_email, subject, status, error, attachment_name, invoice_id, meta, created_at FROM emails"
    params: tuple = ()
    if kind:
        sql += " WHERE kind = ?"
        params = (kind,)
    rows = db.fetch_all(sql + " ORDER BY created_at DESC, id DESC LIMIT ?", params + (limit,))
    for row in rows:
        row["meta"] = db.loads(row["meta"], {})
    return rows


@api.get("/emails/{email_id}/html", response_class=HTMLResponse)
def email_html(email_id: int) -> HTMLResponse:
    row = db.fetch_one("SELECT html FROM emails WHERE id = ?", (email_id,))
    if not row:
        raise services.NotFound("Email introuvable")
    return HTMLResponse(row["html"], headers={
        "Content-Security-Policy": "default-src 'none'; img-src * data:; style-src 'unsafe-inline'",
        "X-Frame-Options": "SAMEORIGIN",
    })


app.include_router(public)
app.include_router(api)
app.include_router(admin)


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
