# SPDX-License-Identifier: AGPL-3.0-or-later
"""Droits d'accès : rôles, niveaux par module, dérogations par utilisateur.

Niveau effectif d'un utilisateur sur un module (voir docs/modules.md) :
module inactif → aucun ; administrateur → gestion ; sinon dérogation de l'utilisateur,
à défaut niveau de son rôle pour ce module, à défaut niveau par défaut du rôle, à défaut aucun.
L'Accueil et les Paramètres sont toujours visibles en lecture (chacun gère son compte).
"""

from __future__ import annotations

from .. import db
from . import modules as registry
from .errors import Conflict, NotFound
from .modules import LEVEL_NAMES, MANAGE, NONE, READ, WRITE

__all__ = ["NONE", "READ", "WRITE", "MANAGE", "LEVEL_NAMES", "levels_for", "level_for", "parse_level"]


def parse_level(value: object) -> int:
    """« read », 1, "1"… → niveau entier. Tout le reste est refusé."""
    if isinstance(value, bool):
        raise ValueError("Niveau de droit invalide.")
    if isinstance(value, int) and NONE <= value <= MANAGE:
        return value
    if isinstance(value, str):
        names = {name: level for level, name in LEVEL_NAMES.items()}
        if value in names:
            return names[value]
        if value.isdigit() and NONE <= int(value) <= MANAGE:
            return int(value)
    raise ValueError("Niveau de droit invalide.")


def levels_for(user: dict | None) -> dict[str, int]:
    """Niveau effectif de l'utilisateur sur chaque module enregistré."""
    modules = registry.load()
    if not user:
        return {key: NONE for key in modules}
    active = registry.enabled_keys()
    if user.get("role") == "admin":
        return {key: (MANAGE if key in active else NONE) for key in modules}
    role = None
    role_levels: dict[str, int] = {}
    if user.get("role_id"):
        role = db.fetch_one("SELECT id, default_level FROM roles WHERE id = ?", (user["role_id"],))
        if role:
            role_levels = {r["module"]: r["level"] for r in
                           db.fetch_all("SELECT module, level FROM role_permissions WHERE role_id = ?", (role["id"],))}
    overrides = {r["module"]: r["level"] for r in
                 db.fetch_all("SELECT module, level FROM user_permissions WHERE user_id = ?", (user["id"],))}
    out = {}
    for key, module in modules.items():
        if key not in active:
            out[key] = NONE
            continue
        if key in overrides:
            level = overrides[key]
        elif key in role_levels:
            level = role_levels[key]
        else:
            level = role["default_level"] if role else NONE
        if module.core:
            # Accueil et Paramètres : toujours visibles ; les réglages de l'instance restent aux administrateurs
            level = max(level, READ) if key == "home" else READ
        out[key] = level
    return out


def level_for(user: dict | None, module: str) -> int:
    return levels_for(user).get(module, NONE)


# ═════════════════════════════════════════════════════════════════════════
# Rôles
# ═════════════════════════════════════════════════════════════════════════
def _role(row: dict) -> dict:
    perms = {r["module"]: r["level"] for r in
             db.fetch_all("SELECT module, level FROM role_permissions WHERE role_id = ?", (row["id"],))}
    users = db.fetch_one("SELECT COUNT(*) AS n FROM users WHERE role_id = ?", (row["id"],))["n"]
    return {"id": row["id"], "key": row["key"], "name": row["name"], "description": row["description"],
            "default_level": row["default_level"], "is_system": bool(row["is_system"]), "permissions": perms,
            "users": users}


def list_roles() -> list[dict]:
    return [_role(r) for r in db.fetch_all("SELECT * FROM roles ORDER BY is_system DESC, name COLLATE NOCASE")]


def get_role(role_id: int) -> dict:
    row = db.fetch_one("SELECT * FROM roles WHERE id = ?", (role_id,))
    if not row:
        raise NotFound("Rôle introuvable")
    return _role(row)


def _clean_permissions(raw: object) -> dict[str, int]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("Droits invalides.")
    modules = registry.load()
    clean = {}
    for key, value in raw.items():
        if key not in modules or modules[key].core:
            continue  # Accueil et Paramètres ne se règlent pas par rôle
        clean[key] = parse_level(value)
    return clean


def _role_values(data: dict, existing: dict | None = None) -> dict:
    values = {}
    if "name" in data or existing is None:
        name = str(data.get("name") or "").strip()[:60]
        if not name:
            raise ValueError("Donnez un nom au rôle.")
        other = db.fetch_one("SELECT id FROM roles WHERE name = ? COLLATE NOCASE", (name,))
        if other and (existing is None or other["id"] != existing["id"]):
            raise ValueError("Un rôle porte déjà ce nom.")
        values["name"] = name
    if "description" in data:
        values["description"] = str(data.get("description") or "").strip()[:240]
    if "default_level" in data:
        values["default_level"] = parse_level(data["default_level"])
    return values


def _save_permissions(role_id: int, permissions: dict[str, int]) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM role_permissions WHERE role_id = ?", (role_id,))
        conn.executemany("INSERT INTO role_permissions (role_id, module, level) VALUES (?, ?, ?)",
                         [(role_id, key, level) for key, level in permissions.items()])


def create_role(data: dict) -> dict:
    values = _role_values(data)
    permissions = _clean_permissions(data.get("permissions"))
    role_id = db.insert("roles", {**values, "is_system": 0, "created_at": db.now_iso()})
    _save_permissions(role_id, permissions)
    return get_role(role_id)


def update_role(role_id: int, data: dict) -> dict:
    role = get_role(role_id)
    values = _role_values(data, role)
    if values:
        db.update("roles", role_id, values)
    if "permissions" in data:
        _save_permissions(role_id, _clean_permissions(data["permissions"]))
    return get_role(role_id)


def delete_role(role_id: int) -> None:
    role = get_role(role_id)
    if role["is_system"]:
        raise Conflict("Ce rôle est fourni avec Caffein : il ne peut pas être supprimé.")
    if role["users"]:
        raise Conflict(f"{role['users']} utilisateur(s) ont ce rôle : attribuez-leur un autre rôle d'abord.")
    db.execute("DELETE FROM roles WHERE id = ?", (role_id,))


def default_role_id() -> int | None:
    row = db.fetch_one("SELECT id FROM roles WHERE key = 'team'")
    return row["id"] if row else None


# ═════════════════════════════════════════════════════════════════════════
# Dérogations par utilisateur
# ═════════════════════════════════════════════════════════════════════════
def user_overrides(user_id: int) -> dict[str, int]:
    return {r["module"]: r["level"] for r in
            db.fetch_all("SELECT module, level FROM user_permissions WHERE user_id = ?", (user_id,))}


def set_user_overrides(user_id: int, overrides: object) -> dict[str, int]:
    """Remplace les dérogations de l'utilisateur. `None` pour un module = suivre son rôle."""
    if not isinstance(overrides, dict):
        raise ValueError("Droits invalides.")
    modules = registry.load()
    clean = {}
    for key, value in overrides.items():
        if key not in modules or modules[key].core or value is None:
            continue
        clean[key] = parse_level(value)
    with db.connect() as conn:
        conn.execute("DELETE FROM user_permissions WHERE user_id = ?", (user_id,))
        conn.executemany("INSERT INTO user_permissions (user_id, module, level) VALUES (?, ?, ?)",
                         [(user_id, key, level) for key, level in clean.items()])
    return clean


__all__ += ["list_roles", "get_role", "create_role", "update_role", "delete_role", "default_role_id",
            "user_overrides", "set_user_overrides", "WRITE"]
