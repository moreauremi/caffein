# SPDX-License-Identifier: AGPL-3.0-or-later
"""Dépendances FastAPI communes : utilisateur connecté, administrateur, droits sur un module."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .. import auth, config
from . import modules as registry
from .permissions import READ, WRITE, level_for

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def current_user(request: Request) -> dict:
    user = auth.user_from_token(request.cookies.get(auth.COOKIE_NAME))
    if not user:
        raise HTTPException(401, "Connexion requise.")
    return user


def admin_user(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Action réservée aux administrateurs.")
    return user


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def open_session(response: Response, request: Request, user: dict) -> None:
    token = auth.create_session(user["id"], client_ip(request), request.headers.get("user-agent", ""))
    response.set_cookie(auth.COOKIE_NAME, token, max_age=config.SESSION_DAYS * 86400, httponly=True,
                        samesite="lax", secure=config.SECURE_COOKIES, path="/")


def check_access(user: dict, module: str, level: int) -> None:
    """404 si le module est désactivé (il n'existe pas pour l'utilisateur), 403 si le niveau manque."""
    if not registry.is_enabled(module):
        raise HTTPException(404, "Ce module n'est pas activé.")
    if level_for(user, module) < level:
        raise HTTPException(403, "Vous n'avez pas les droits nécessaires sur ce module.")


def require(module: str, level: int = READ):
    """Dépendance : `user: dict = Depends(require("sales", WRITE))`."""
    def dependency(user: dict = Depends(current_user)) -> dict:
        check_access(user, module, level)
        return user
    return dependency


def module_router(module: str) -> APIRouter:
    """Routeur d'un module : lecture pour GET, écriture pour les autres méthodes. Une route qui demande
    davantage (gestion) ajoute sa propre dépendance `require(module, MANAGE)`."""
    def access(request: Request, user: dict = Depends(current_user)) -> dict:
        check_access(user, module, READ if request.method in SAFE_METHODS else WRITE)
        return user
    return APIRouter(prefix="/api", dependencies=[Depends(access)])
