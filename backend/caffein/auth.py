# SPDX-License-Identifier: AGPL-3.0-or-later
"""Comptes utilisateurs et sessions.

- Mots de passe hachés avec scrypt (bibliothèque standard, sel aléatoire par compte).
- Sessions côté serveur : le cookie contient un jeton aléatoire, la base n'en garde
  que l'empreinte SHA-256 ; une session est révocable (déconnexion, désactivation).
- Limitation des tentatives de connexion par adresse IP.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from datetime import datetime, timedelta

from . import config, db

COOKIE_NAME = "caffein_session"
ROLES = ("admin", "member")

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 64}


class AuthError(Exception):
    pass


# ── Mots de passe ────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt_b64), **_SCRYPT)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def check_password_strength(password: str) -> None:
    if len(password or "") < config.PASSWORD_MIN_LENGTH:
        raise ValueError(f"Le mot de passe doit contenir au moins {config.PASSWORD_MIN_LENGTH} caractères.")


# ── Utilisateurs ─────────────────────────────────────────────────────────
PUBLIC_FIELDS = "id, email, full_name, role, role_id, active, is_demo, last_login_at, created_at"


def _public(row: dict | None) -> dict | None:
    if row is None:
        return None
    row = {k: row[k] for k in ("id", "email", "full_name", "role", "role_id", "active", "is_demo", "last_login_at",
                               "created_at")}
    row["active"] = bool(row["active"])
    row["is_demo"] = bool(row["is_demo"])
    return row


def _clean_role_id(value: object) -> int | None:
    """Rôle d'un membre (droits par module, voir core/permissions.py). Vide : le rôle « Équipe »."""
    if value in (None, ""):
        row = db.fetch_one("SELECT id FROM roles WHERE key = 'team'")
        return row["id"] if row else None
    if isinstance(value, bool):
        raise ValueError("Rôle inconnu.")
    try:
        role_id = int(value)
    except (TypeError, ValueError):
        raise ValueError("Rôle inconnu.") from None
    if not db.fetch_one("SELECT id FROM roles WHERE id = ?", (role_id,)):
        raise ValueError("Rôle inconnu.")
    return role_id


def count_users() -> int:
    return db.fetch_one("SELECT COUNT(*) AS n FROM users")["n"]


def list_users() -> list[dict]:
    return [_public(r) for r in db.fetch_all(f"SELECT {PUBLIC_FIELDS} FROM users ORDER BY role, full_name COLLATE NOCASE")]


def get_user(user_id: int) -> dict | None:
    return _public(db.fetch_one(f"SELECT {PUBLIC_FIELDS} FROM users WHERE id = ?", (user_id,)))


def get_user_by_email(email: str) -> dict | None:
    return db.fetch_one("SELECT * FROM users WHERE email = ?", ((email or "").strip(),))


def _clean_email(email: str) -> str:
    email = (email or "").strip().lower()
    if "@" not in email or len(email) > 200 or " " in email:
        raise ValueError("Adresse email invalide.")
    return email


def create_user(email: str, password: str, full_name: str = "", role: str = "member", is_demo: bool = False,
                role_id: object = None) -> dict:
    email = _clean_email(email)
    if role not in ROLES:
        raise ValueError("Rôle inconnu.")
    check_password_strength(password)
    if get_user_by_email(email):
        raise ValueError("Un compte existe déjà avec cette adresse email.")
    user_id = db.insert("users", {
        "email": email, "full_name": (full_name or "").strip()[:120], "password_hash": hash_password(password),
        "role": role, "role_id": _clean_role_id(role_id), "active": 1, "is_demo": int(is_demo), "created_at": db.now_iso(),
    })
    return get_user(user_id)


def update_user(user_id: int, values: dict, acting_user: dict | None = None) -> dict:
    user = get_user(user_id)
    if not user:
        raise LookupError("Utilisateur introuvable.")
    clean: dict = {}
    if "email" in values:
        email = _clean_email(values["email"])
        other = get_user_by_email(email)
        if other and other["id"] != user_id:
            raise ValueError("Un compte existe déjà avec cette adresse email.")
        clean["email"] = email
    if "full_name" in values:
        clean["full_name"] = str(values["full_name"] or "").strip()[:120]
    if "role" in values:
        if values["role"] not in ROLES:
            raise ValueError("Rôle inconnu.")
        clean["role"] = values["role"]
    if "role_id" in values or (clean.get("role") == "member" and not user.get("role_id")):
        clean["role_id"] = _clean_role_id(values.get("role_id"))
    if "active" in values:
        clean["active"] = int(bool(values["active"]))
    # On ne peut pas retirer le dernier administrateur actif
    demoting = clean.get("role", user["role"]) != "admin" or not clean.get("active", user["active"])
    if user["role"] == "admin" and user["active"] and demoting and _active_admins() <= 1:
        raise ValueError("Impossible : il doit rester au moins un administrateur actif.")
    if acting_user and acting_user["id"] == user_id and demoting:
        raise ValueError("Vous ne pouvez pas retirer vos propres droits d'administrateur.")
    db.update("users", user_id, clean)
    if clean.get("active") == 0:
        revoke_sessions(user_id)
    return get_user(user_id)


def delete_user(user_id: int, acting_user: dict) -> None:
    user = get_user(user_id)
    if not user:
        raise LookupError("Utilisateur introuvable.")
    if user_id == acting_user["id"]:
        raise ValueError("Vous ne pouvez pas supprimer votre propre compte.")
    if user["role"] == "admin" and user["active"] and _active_admins() <= 1:
        raise ValueError("Impossible : il doit rester au moins un administrateur actif.")
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))


def set_password(user_id: int, password: str) -> None:
    check_password_strength(password)
    db.update("users", user_id, {"password_hash": hash_password(password)})
    revoke_sessions(user_id)


def _active_admins() -> int:
    return db.fetch_one("SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND active = 1")["n"]


# ── Sessions ─────────────────────────────────────────────────────────────
def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def create_session(user_id: int, ip: str = "", user_agent: str = "") -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(config.TIMEZONE).replace(microsecond=0)
    db.insert("sessions", {
        "token_hash": _token_hash(token), "user_id": user_id, "created_at": now.isoformat(),
        "expires_at": (now + timedelta(days=config.SESSION_DAYS)).isoformat(), "last_seen_at": now.isoformat(),
        "ip": ip[:64], "user_agent": user_agent[:250],
    })
    db.update("users", user_id, {"last_login_at": now.isoformat()})
    return token


def user_from_token(token: str | None) -> dict | None:
    if not token:
        return None
    row = db.fetch_one(
        """SELECT u.*, s.expires_at, s.last_seen_at FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token_hash = ?""", (_token_hash(token),))
    if not row or not row["active"]:
        return None
    now = datetime.now(config.TIMEZONE)
    if datetime.fromisoformat(row["expires_at"]) < now:
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
        return None
    # « last_seen » rafraîchi au plus une fois par heure (évite une écriture par requête)
    if now - datetime.fromisoformat(row["last_seen_at"]) > timedelta(hours=1):
        db.execute("UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?", (now.replace(microsecond=0).isoformat(), _token_hash(token)))
    return _public(row)


def delete_session(token: str | None) -> None:
    if token:
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def revoke_sessions(user_id: int) -> None:
    db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def purge_expired_sessions() -> None:
    db.execute("DELETE FROM sessions WHERE expires_at < ?", (db.now_iso(),))


# ── Connexion ────────────────────────────────────────────────────────────
_failures: dict[str, list[float]] = {}
_failures_lock = threading.Lock()


def _throttled(key: str) -> bool:
    cutoff = time.monotonic() - config.LOGIN_WINDOW_SECONDS
    with _failures_lock:
        recent = [t for t in _failures.get(key, []) if t > cutoff]
        _failures[key] = recent
        return len(recent) >= config.LOGIN_MAX_FAILURES


def _record_failure(key: str) -> None:
    with _failures_lock:
        _failures.setdefault(key, []).append(time.monotonic())


def authenticate(email: str, password: str, ip: str = "") -> dict:
    # clé IP + compte : derrière un proxy, une attaque sur un compte ne bloque pas les autres
    key = f"{ip}|{(email or '').strip().lower()}"
    if _throttled(key):
        raise AuthError("Trop de tentatives. Réessayez dans quelques minutes.")
    row = get_user_by_email(email)
    # vérification même si le compte n'existe pas (temps de réponse constant)
    valid = verify_password(password or "", row["password_hash"] if row else hash_password("leurre-temps-constant"))
    if not row or not valid or not row["active"]:
        _record_failure(key)
        raise AuthError("Email ou mot de passe incorrect.")
    with _failures_lock:
        _failures.pop(key, None)
    return _public(row)


def ensure_demo_user() -> dict:
    """Compte utilisé par le bouton « Accès démo » (CAFFEIN_DEMO=1)."""
    row = db.fetch_one("SELECT * FROM users WHERE is_demo = 1 ORDER BY id LIMIT 1")
    if row:
        return _public(row)
    from .services import get_profile  # import local : services n'importe pas auth

    name = get_profile().get("full_name") or "Visiteur"
    return create_user("demo@caffein.local", secrets.token_urlsafe(24), name, "admin", is_demo=True)
