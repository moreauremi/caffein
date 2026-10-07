# SPDX-License-Identifier: AGPL-3.0-or-later
from caffein import auth, db

from .conftest import ADMIN, ensure_admin


def test_api_requires_login(anon):
    assert anon.get("/api/health").status_code == 200
    assert anon.get("/api/home").status_code == 401
    assert anon.get("/api/invoices").status_code == 401
    assert anon.get("/api/setup/status").json() == {"needs_setup": False, "demo": False, "version": anon.get("/api/health").json()["version"]}


def test_login_logout(anon):
    assert anon.post("/api/auth/login", json={"email": ADMIN["email"], "password": "faux"}).status_code == 401
    res = anon.post("/api/auth/login", json={"email": ADMIN["email"].upper(), "password": ADMIN["password"]})
    assert res.status_code == 200 and "httponly" in res.headers["set-cookie"].lower()
    assert anon.get("/api/auth/me").json()["email"] == ADMIN["email"]
    assert anon.post("/api/auth/logout").status_code == 204
    assert anon.get("/api/home").status_code == 401


def test_login_throttling(anon):
    for _ in range(5):
        anon.post("/api/auth/login", json={"email": ADMIN["email"], "password": "faux"})
    res = anon.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
    assert res.status_code == 401 and "tentatives" in res.json()["detail"]
    auth._failures.clear()


def test_demo_login_disabled_by_default(anon):
    assert anon.post("/api/auth/demo").status_code == 404


def test_csrf_origin_check(client):
    res = client.put("/api/profile", json={"company": "Pirate"}, headers={"Origin": "https://evil.example"})
    assert res.status_code == 403
    assert client.put("/api/profile", json={"company": "Studio Test"}, headers={"Origin": "http://testserver"}).status_code == 200


def test_member_permissions(client):
    member = client.post("/api/users", json={"email": "membre@test.local", "password": "motdepasse-membre",
                                              "full_name": "Membre", "role": "member"})
    assert member.status_code == 201
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"email": "membre@test.local", "password": "motdepasse-membre"})
    assert client.get("/api/home").status_code == 200
    assert client.post("/api/invoices/assistant", json={"text": "Logo pour Atelier Nova, 500 €"}).status_code == 201
    assert client.put("/api/profile", json={"company": "X"}).status_code == 403
    assert client.get("/api/users").status_code == 403
    assert client.post("/api/admin/reset", json={}).status_code == 403
    client.post("/api/auth/logout")
    db.execute("DELETE FROM users WHERE email = 'membre@test.local'")


def test_admin_safeguards(client):
    me = client.get("/api/auth/me").json()
    assert client.delete(f"/api/users/{me['id']}").status_code == 400
    assert client.put(f"/api/users/{me['id']}", json={"role": "member"}).status_code == 400
    assert client.post("/api/users", json={"email": "court@test.local", "password": "123"}).status_code == 400


def test_password_change(client):
    bad = client.post("/api/auth/password", json={"current_password": "faux", "new_password": "nouveau-mdp-1"})
    assert bad.status_code == 400
    ok = client.post("/api/auth/password", json={"current_password": ADMIN["password"], "new_password": "nouveau-mdp-1"})
    assert ok.status_code == 200
    assert client.get("/api/auth/me").status_code == 200  # la session courante est rouverte
    ensure_admin()


def test_setup_wizard_on_fresh_instance(anon):
    db.execute("DELETE FROM users")
    assert anon.get("/api/setup/status").json()["needs_setup"] is True
    payload = {
        "organization": {"company": "Atelier Neuf", "siret": "111 222 333 00044", "activity": "bic_services", "vat_exempt": True},
        "admin": {"full_name": "Camille Neuf", "email": "camille@neuf.example", "password": "un-long-mot-de-passe"},
        "demo_data": False,
    }
    res = anon.post("/api/setup", json=payload)
    assert res.status_code == 201, res.text
    assert anon.get("/api/auth/me").json()["role"] == "admin"
    profile = anon.get("/api/profile").json()
    assert profile["company"] == "Atelier Neuf" and profile["vat_exempt"] is True
    assert anon.get("/api/invoices").json() == []
    assert len(anon.get("/api/notifications").json()) == 4
    assert anon.post("/api/setup", json=payload).status_code == 409
    ensure_admin()
