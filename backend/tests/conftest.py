# SPDX-License-Identifier: AGPL-3.0-or-later
"""Isolation des tests : base, dossiers et clé dans un répertoire temporaire, IA et emails hors-ligne."""

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="caffein-tests-")
os.environ["CAFFEIN_DATA_DIR"] = _tmp
os.environ["CAFFEIN_SCHEDULER"] = "0"
os.environ["CAFFEIN_AI"] = "0"
os.environ["CAFFEIN_DEMO"] = "0"
os.environ["CAFFEIN_APP_URL"] = "http://testserver"
for name in ("RESEND_API_KEY", "CAFFEIN_SMTP_HOST", "CAFFEIN_ENCRYPTION_KEY"):
    os.environ[name] = ""

import pytest  # noqa: E402

from caffein import auth, db  # noqa: E402
from caffein.seed import seed  # noqa: E402

ADMIN = {"email": "admin@test.local", "password": "motdepasse-admin", "full_name": "Admin Test"}


def ensure_admin() -> dict:
    row = auth.get_user_by_email(ADMIN["email"])
    if row:
        auth.update_user(row["id"], {"active": True, "role": "admin"})
        auth.set_password(row["id"], ADMIN["password"])
        return auth.get_user(row["id"])
    return auth.create_user(ADMIN["email"], ADMIN["password"], ADMIN["full_name"], "admin")


@pytest.fixture()
def demo():
    """Base de démonstration fraîche pour chaque test (les comptes sont conservés)."""
    db.init_db()
    seed(reset=True)
    auth._failures.clear()
    yield ensure_admin()


@pytest.fixture()
def anon(demo):
    from fastapi.testclient import TestClient

    from caffein.api.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def client(anon):
    res = anon.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
    assert res.status_code == 200, res.text
    return anon
