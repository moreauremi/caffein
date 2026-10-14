# SPDX-License-Identifier: AGPL-3.0-or-later
"""Outils communs aux tests des modules."""

from fastapi.testclient import TestClient

from caffein import auth, db
from caffein.core import permissions

PASSWORD = "motdepasse-membre"


def login_as(email: str, password: str = PASSWORD) -> TestClient:
    from caffein.api.main import app

    c = TestClient(app)
    res = c.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return c


def make_member(email: str, role_key: str = "readonly", overrides: dict | None = None) -> dict:
    """Membre avec un rôle fourni (« readonly », « team »…) et des dérogations éventuelles."""
    row = auth.get_user_by_email(email)
    if row:
        db.execute("DELETE FROM users WHERE id = ?", (row["id"],))
    role = db.fetch_one("SELECT id FROM roles WHERE key = ?", (role_key,))
    user = auth.create_user(email, PASSWORD, "Membre", "member", role_id=role["id"] if role else None)
    if overrides:
        permissions.set_user_overrides(user["id"], overrides)
    return auth.get_user(user["id"])


def article_id(name: str) -> int:
    return db.fetch_one("SELECT id FROM technical_articles WHERE name = ?", (name,))["id"]


def disable_module(client, key: str) -> None:
    """Désactive un module par l'API, après ceux qui en dépendent (on ne peut pas faire autrement)."""
    from caffein.core import modules as registry

    for module in registry.load().values():
        if key in module.depends and registry.is_enabled(module.key):
            disable_module(client, module.key)
    res = client.put(f"/api/settings/modules/{key}", json={"enabled": False})
    assert res.status_code == 200, res.text
