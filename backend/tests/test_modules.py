# SPDX-License-Identifier: AGPL-3.0-or-later
"""Socle modulaire : registre et activation des modules, droits (rôles, dérogations), moteur de données,
événements entre modules, mise à jour d'une instance d'avant les modules."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from caffein import auth, db, services
from caffein.core import events, permissions
from caffein.core import modules as registry
from caffein.utils import today

PASSWORD = "motdepasse-membre"


def login_as(email: str, password: str = PASSWORD) -> TestClient:
    from caffein.api.main import app

    c = TestClient(app)
    res = c.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return c


def make_member(email: str, role_id: int | None = None, overrides: dict | None = None) -> dict:
    row = auth.get_user_by_email(email)
    if row:
        db.execute("DELETE FROM users WHERE id = ?", (row["id"],))
    user = auth.create_user(email, PASSWORD, "Membre", "member", role_id=role_id)
    if overrides:
        permissions.set_user_overrides(user["id"], overrides)
    return auth.get_user(user["id"])


def role_id(key: str) -> int:
    return db.fetch_one("SELECT id FROM roles WHERE key = ?", (key,))["id"]


@pytest.fixture()
def restore_modules():
    yield
    registry.enable_all()


# ═════════════════════════════════════════════════════════════════════════
# Registre et description de l'espace
# ═════════════════════════════════════════════════════════════════════════
def test_registry_is_consistent():
    modules = registry.load()
    assert {"home", "sales", "accounting", "settings"} <= set(modules)
    keys = [m.key for m in registry.dependency_order()]
    for module in modules.values():
        for dep in module.depends:
            assert keys.index(dep) < keys.index(module.key)
    slugs = [m.slug for m in modules.values()]
    assert len(slugs) == len(set(slugs))
    assert registry.get("home").core and registry.get("settings").core


def test_meta_for_admin(client):
    meta = client.get("/api/meta").json()
    assert meta["is_admin"] is True
    keys = [m["key"] for m in meta["modules"]]
    assert keys[0] == "home" and keys[-1] == "settings" and "sales" in keys and "accounting" in keys
    home = next(m for m in meta["modules"] if m["key"] == "home")
    assert home["pages"][0]["path"] == "/"
    orders = meta["entities"]["sales.orders"]
    assert orders["can_delete"] and orders["actions"] and orders["children"][0]["key"] == "lines"
    assert "invoice_id" not in [f["name"] for f in orders["fields"]]  # champ caché
    settings = next(m for m in meta["modules"] if m["key"] == "settings")
    assert {"utilisateurs", "roles", "modules"} <= {p["slug"] for p in settings["pages"]}


# ═════════════════════════════════════════════════════════════════════════
# Activation des modules
# ═════════════════════════════════════════════════════════════════════════
def test_disabled_module_disappears(client, restore_modules):
    assert client.get("/api/invoices").status_code == 200
    res = client.put("/api/settings/modules/sales", json={"enabled": False})
    assert res.status_code == 200 and not next(m for m in res.json() if m["key"] == "sales")["enabled"]
    assert client.get("/api/invoices").status_code == 404
    assert client.get("/api/data/sales/orders").status_code == 404
    assert "sales" not in [m["key"] for m in client.get("/api/meta").json()["modules"]]
    assert not [k for k in client.get("/api/home").json()["kpis"] if k["module"] == "sales"]
    # les liens publics des factures restent valables
    inv = next(i for i in services.list_invoices("invoice") if i["status"] != "draft")
    assert client.get(f"/api/public/invoices/{inv['public_token']}").status_code == 200
    assert client.put("/api/settings/modules/sales", json={"enabled": True}).status_code == 200
    assert client.get("/api/invoices").status_code == 200


def test_core_modules_cannot_be_disabled(client):
    assert client.put("/api/settings/modules/home", json={"enabled": False}).status_code == 409
    assert client.put("/api/settings/modules/settings", json={"enabled": False}).status_code == 409
    assert client.put("/api/settings/modules/nope", json={"enabled": False}).status_code == 404
    assert client.put("/api/settings/modules/sales", json={"enabled": "non"}).status_code == 400


def test_dependencies_are_enforced(restore_modules, monkeypatch):
    sales = registry.get("sales")
    monkeypatch.setattr(sales, "depends", ("accounting",))
    registry.set_enabled("sales", False)
    registry.set_enabled("accounting", False)
    with pytest.raises(Exception, match="Activez d'abord"):
        registry.set_enabled("sales", True)
    registry.set_enabled("accounting", True)
    registry.set_enabled("sales", True)
    with pytest.raises(Exception, match="Désactivez d'abord"):
        registry.set_enabled("accounting", False)


def test_module_selection_follows_dependencies(demo, restore_modules, monkeypatch):
    monkeypatch.setattr(registry.get("sales"), "depends", ("accounting",))
    registry.set_selection(["sales"])
    assert registry.is_enabled("sales") and registry.is_enabled("accounting") and registry.is_enabled("home")
    registry.set_selection([])
    assert not registry.is_enabled("sales") and registry.is_enabled("settings")
    with pytest.raises(ValueError):
        registry.set_selection("sales")


def test_jobs_follow_their_module(demo, restore_modules):
    from caffein.jobs import describe_jobs, job_enabled, job_module

    assert job_module("process_inbox") == "accounting" and job_module("send_invoice") == "sales"
    registry.set_enabled("accounting", False)
    assert not job_enabled("process_inbox") and job_enabled("send_invoice")
    assert "process_inbox" not in [j["name"] for j in describe_jobs()]


# ═════════════════════════════════════════════════════════════════════════
# Droits : rôles, niveaux, dérogations
# ═════════════════════════════════════════════════════════════════════════
def test_parse_level():
    assert permissions.parse_level("write") == 2 and permissions.parse_level(3) == 3 and permissions.parse_level("1") == 1
    for bad in (True, 4, -1, "admin", None, 1.5):
        with pytest.raises(ValueError):
            permissions.parse_level(bad)


def test_member_with_role(client):
    role = client.post("/api/settings/roles", json={"name": "Lecture ventes", "permissions": {"sales": "read"}}).json()
    make_member("vente@test.local", role["id"])
    member = login_as("vente@test.local")
    assert member.get("/api/invoices").status_code == 200
    assert member.post("/api/invoices", json={"kind": "invoice"}).status_code == 403
    assert member.post("/api/data/sales/orders", json={}).status_code == 403
    assert member.get("/api/tva").status_code == 403            # module actif, mais aucun droit
    assert member.get("/api/users").status_code == 403          # paramètres de l'instance : administrateurs
    assert member.get("/api/settings/modules").status_code == 403
    meta = member.get("/api/meta").json()
    assert [m["key"] for m in meta["modules"]] == ["home", "sales", "settings"]
    settings = next(m for m in meta["modules"] if m["key"] == "settings")
    assert {p["slug"] for p in settings["pages"]} == {"compte", "apparence", "automatisations", "a-propos"}
    assert meta["entities"]["sales.orders"]["can_create"] is False
    kpis = member.get("/api/home").json()
    assert {k["module"] for k in kpis["kpis"]} == {"home", "sales"} and kpis["shortcuts"] == []
    assert kpis["next_deadlines"] == []                         # échéances : Comptabilité


def test_user_overrides(client):
    user = make_member("derog@test.local", role_id("readonly"))
    member = login_as("derog@test.local")
    assert member.get("/api/tva").status_code == 200 and member.post("/api/data/sales/orders", json={}).status_code == 403
    res = client.put(f"/api/users/{user['id']}/permissions", json={"overrides": {"accounting": 0, "sales": "write"}})
    assert res.status_code == 200
    levels = res.json()["user"]["levels"]
    assert levels["accounting"] == 0 and levels["sales"] == 2 and levels["home"] == 1 and levels["settings"] == 1
    assert member.get("/api/tva").status_code == 403
    assert member.post("/api/data/sales/orders", json={"client_id": services.list_clients()[0]["id"]}).status_code == 201
    # null : suivre le rôle ; un module socle ne se règle pas
    client.put(f"/api/users/{user['id']}/permissions", json={"overrides": {"accounting": None, "home": 0}})
    assert permissions.user_overrides(user["id"]) == {}
    assert member.get("/api/tva").status_code == 200
    assert client.put(f"/api/users/{user['id']}/permissions", json={"overrides": {"sales": 9}}).status_code == 400


def test_admin_has_everything_on_active_modules(demo):
    levels = permissions.levels_for(demo)
    assert all(level == permissions.MANAGE for level in levels.values())


def test_member_role_assignment(client):
    created = client.post("/api/users", json={"email": "nouveau@test.local", "password": PASSWORD, "full_name": "N"})
    assert created.status_code == 201
    user = created.json()
    assert user["role_id"] == role_id("team") and user["levels"]["sales"] == 2 and user["levels"]["settings"] == 1
    res = client.put(f"/api/users/{user['id']}", json={"role_id": role_id("accountant")})
    assert res.json()["levels"]["accounting"] == 2 and res.json()["levels"]["sales"] == 1
    assert client.put(f"/api/users/{user['id']}", json={"role_id": 99999}).status_code == 400
    db.execute("DELETE FROM users WHERE id = ?", (user["id"],))


def test_roles_crud(client):
    roles = client.get("/api/settings/roles").json()
    assert {"team", "readonly", "accountant"} <= {r["key"] for r in roles["roles"]}
    assert "home" not in [m["key"] for m in roles["modules"]]   # l'Accueil ne se règle pas par rôle
    created = client.post("/api/settings/roles", json={"name": "Stagiaire", "default_level": 1,
                                                       "permissions": {"sales": 2, "home": 0, "inconnu": 3}})
    assert created.status_code == 201
    role = created.json()
    assert role["permissions"] == {"sales": 2} and role["default_level"] == 1
    assert client.post("/api/settings/roles", json={"name": "stagiaire"}).status_code == 400  # nom déjà pris
    updated = client.put(f"/api/settings/roles/{role['id']}", json={"permissions": {"accounting": "manage"}}).json()
    assert updated["permissions"] == {"accounting": 3}
    team = role_id("team")
    assert client.delete(f"/api/settings/roles/{team}").status_code == 409          # rôle fourni
    make_member("stagiaire@test.local", role["id"])
    assert client.delete(f"/api/settings/roles/{role['id']}").status_code == 409    # rôle utilisé
    db.execute("DELETE FROM users WHERE email = 'stagiaire@test.local'")
    assert client.delete(f"/api/settings/roles/{role['id']}").status_code == 204


def test_last_admin_and_self_protection(client):
    me = client.get("/api/auth/me").json()
    assert client.put(f"/api/users/{me['id']}", json={"role": "member"}).status_code == 400


# ═════════════════════════════════════════════════════════════════════════
# Moteur de données (commandes clients, clients)
# ═════════════════════════════════════════════════════════════════════════
def _client_id() -> int:
    return services.list_clients()[0]["id"]


def test_order_lifecycle(client):
    lines = [{"description": "Atelier de cadrage", "quantity": 2, "unit_price": 450},
             {"description": "Maquettes", "quantity": "1,5", "unit_price": "300.5"}]
    res = client.post("/api/data/sales/orders", json={"client_id": _client_id(), "lines": lines, "notes": "Urgent"})
    assert res.status_code == 201, res.text
    order = res.json()
    first = db.fetch_one("SELECT COUNT(*) AS n FROM sales_orders")["n"]  # commandes de démonstration comprises
    assert order["code"] == f"CC-{today().year}-{first:04d}" and order["status"] == "draft"
    assert order["total_ht"] == 1350.75 and [line["amount"] for line in order["lines"]] == [900, 450.75]
    assert order["client_id__label"] and order["order_date"] == today().isoformat()
    assert set(order["_actions"]) == {"confirm", "cancel"} and order["_locked"] is None

    # aperçu : calculé par le serveur, rien n'est enregistré
    preview = client.post("/api/data/sales/orders/preview", json={"lines": [{"quantity": 3, "unit_price": 10}]}).json()
    assert preview["computed"]["total_ht"] == 30 and preview["children"]["lines"][0]["amount"] == 30

    edited = client.put(f"/api/data/sales/orders/{order['id']}", json={"lines": lines[:1], "code": "PIRATE"}).json()
    assert edited["total_ht"] == 900 and edited["code"] == order["code"] and edited["notes"] == "Urgent"

    confirmed = client.post(f"/api/data/sales/orders/{order['id']}/actions/confirm").json()
    assert confirmed["row"]["status"] == "confirmed" and "confirmée" in confirmed["message"]
    assert client.put(f"/api/data/sales/orders/{order['id']}", json={"notes": "x"}).status_code == 409
    assert client.post(f"/api/data/sales/orders/{order['id']}/actions/confirm").status_code == 409
    assert client.delete(f"/api/data/sales/orders/{order['id']}").status_code == 409

    invoiced = client.post(f"/api/data/sales/orders/{order['id']}/actions/invoice").json()
    assert invoiced["row"]["status"] == "invoiced" and invoiced["row"]["invoice_number"] == "brouillon"
    invoice = services.get_invoice(db.fetch_one("SELECT invoice_id FROM sales_orders WHERE id = ?", (order["id"],))["invoice_id"])
    assert invoice["status"] == "draft" and invoice["subtotal"] == 900 and invoice["items"][0]["description"] == "Atelier de cadrage"
    assert client.post(f"/api/data/sales/orders/{order['id']}/actions/nope").status_code == 404

    second = client.post("/api/data/sales/orders", json={"client_id": _client_id()}).json()
    assert second["code"] == f"CC-{today().year}-{first + 1:04d}"
    assert client.post(f"/api/data/sales/orders/{second['id']}/actions/confirm").status_code == 400  # sans ligne
    assert client.delete(f"/api/data/sales/orders/{second['id']}").status_code == 204


def test_entity_validation(client):
    def post(data):
        return client.post("/api/data/sales/orders", json=data)

    assert "Client" in post({}).json()["detail"]
    assert post({"client_id": 999999}).status_code == 400
    assert post({"client_id": "abc"}).status_code == 400
    bad_qty = post({"client_id": _client_id(), "lines": [{"description": "x", "quantity": "beaucoup"}]})
    assert bad_qty.status_code == 400 and "ligne 1" in bad_qty.json()["detail"]
    assert post({"client_id": _client_id(), "lines": [{"quantity": 1}]}).status_code == 400  # désignation obligatoire
    assert post({"client_id": _client_id(), "lines": "x"}).status_code == 400
    assert post({"client_id": _client_id(), "order_date": "32/13/2026"}).status_code == 400
    assert post({"client_id": _client_id(), "status": "invoiced"}).json()["status"] == "draft"  # champ en lecture seule
    assert client.post("/api/data/sales/orders", content="[1]", headers={"content-type": "application/json"}).status_code in (400, 422)
    assert client.get("/api/data/sales/inconnue").status_code == 404
    assert client.get("/api/data/sales/orders?size=500").status_code == 422


def test_list_search_filter_sort(client):
    clients = client.get("/api/data/sales/clients?q=nova").json()
    assert clients["total"] == 1 and clients["rows"][0]["name"] == "Atelier Nova"
    assert clients["rows"][0]["invoice_count"] > 0 and clients["rows"][0]["total_paid"] > 0
    assert client.get("/api/data/sales/clients?q=%25").json()["total"] == 0  # « % » est cherché tel quel
    ordered = client.get("/api/data/sales/clients?sort=city&dir=desc").json()["rows"]
    assert [r["city"] for r in ordered] == sorted((r["city"] for r in ordered), reverse=True)
    assert client.get("/api/data/sales/clients?sort=password_hash").status_code == 200  # tri ignoré
    for _ in range(2):
        client.post("/api/data/sales/orders", json={"client_id": _client_id(), "lines": [{"description": "a"}]})
    already = client.get("/api/data/sales/orders?f_status=confirmed").json()["total"]
    first = client.get("/api/data/sales/orders").json()["rows"][0]
    client.post(f"/api/data/sales/orders/{first['id']}/actions/confirm")
    confirmed = client.get("/api/data/sales/orders?f_status=confirmed").json()
    assert confirmed["total"] == already + 1 and confirmed["rows"][0]["id"] == first["id"]
    assert all(r["status"] == "confirmed" for r in confirmed["rows"])
    assert client.get("/api/data/sales/orders?f_status=nope").status_code == 400
    page = client.get("/api/data/sales/clients?size=2&page=2").json()
    assert page["page"] == 2 and len(page["rows"]) == 2 and page["total"] == len(services.list_clients())


def test_client_delete_rules(client):
    used = next(c for c in services.list_clients() if c["invoice_count"])
    assert client.delete(f"/api/data/sales/clients/{used['id']}").status_code == 409
    new = client.post("/api/data/sales/clients", json={"name": "Client éphémère", "email": "eph@test.local"}).json()
    order = client.post("/api/data/sales/orders", json={"client_id": new["id"]}).json()
    assert client.delete(f"/api/clients/{new['id']}").status_code == 409            # commande liée
    assert client.delete(f"/api/data/sales/orders/{order['id']}").status_code == 204
    assert client.delete(f"/api/data/sales/clients/{new['id']}").status_code == 204
    assert client.post("/api/data/sales/clients", json={"name": "X", "email": "pas-un-email"}).status_code == 400


def test_options(client):
    options = client.get("/api/data/sales/clients/options?q=kai").json()
    assert options[0]["label"] == "Kairos Conseil" and options[0]["sublabel"] == "Paris"
    # sans aucun droit sur les Ventes, pas de liste de clients
    make_member("options@test.local", role_id("readonly"), {"sales": 0})
    member = login_as("options@test.local")
    assert member.get("/api/data/sales/clients/options").status_code == 403


def test_events_reach_enabled_subscribers(client, monkeypatch, restore_modules):
    received = []
    monkeypatch.setattr(registry.get("accounting"), "events", {"sales.order_delivered": lambda p: received.append(p) or "Stock mis à jour."})
    order = client.post("/api/data/sales/orders", json={"client_id": _client_id(), "lines": [{"description": "a", "quantity": 2}]}).json()
    client.post(f"/api/data/sales/orders/{order['id']}/actions/confirm")
    delivered = client.post(f"/api/data/sales/orders/{order['id']}/actions/deliver").json()
    assert delivered["row"]["status"] == "delivered" and "Stock mis à jour." in delivered["message"]
    assert received[0]["code"] == order["code"] and received[0]["lines"][0]["quantity"] == 2
    assert "accounting" in events.subscribers("sales.order_delivered")
    registry.set_enabled("accounting", False)
    assert "accounting" not in events.subscribers("sales.order_delivered")


def test_subscriber_error_cancels_the_action(client, monkeypatch):
    def refuse(_payload):
        raise ValueError("Stock insuffisant.")

    monkeypatch.setattr(registry.get("accounting"), "events", {"sales.order_delivered": refuse})
    order = client.post("/api/data/sales/orders", json={"client_id": _client_id(), "lines": [{"description": "a"}]}).json()
    client.post(f"/api/data/sales/orders/{order['id']}/actions/confirm")
    res = client.post(f"/api/data/sales/orders/{order['id']}/actions/deliver")
    assert res.status_code == 400 and res.json()["detail"] == "Stock insuffisant."
    assert client.get(f"/api/data/sales/orders/{order['id']}").json()["status"] == "confirmed"


# ═════════════════════════════════════════════════════════════════════════
# Factures : lignes en table, aperçu calculé par le serveur
# ═════════════════════════════════════════════════════════════════════════
def test_invoice_lines_are_rows(client):
    inv = client.post("/api/invoices", json={"kind": "invoice", "client_id": _client_id(), "items": [
        {"description": "Logo", "quantity": 1, "unit_price": 450}, {"description": " ", "quantity": 1, "unit_price": 99},
        {"description": "Charte", "quantity": "2", "unit_price": "100,5"}]}).json()
    assert [i["description"] for i in inv["items"]] == ["Logo", "Charte"] and inv["subtotal"] == 651
    rows = db.fetch_all("SELECT description, position FROM invoice_lines WHERE invoice_id = ? ORDER BY position", (inv["id"],))
    assert [(r["description"], r["position"]) for r in rows] == [("Logo", 0), ("Charte", 1)]
    assert db.fetch_one("SELECT items FROM invoices WHERE id = ?", (inv["id"],))["items"] == "[]"
    updated = client.put(f"/api/invoices/{inv['id']}", json={"title": "Identité"}).json()
    assert len(updated["items"]) == 2 and updated["subtotal"] == 651  # lignes conservées
    for bad in ([{"description": "x", "quantity": "Infinity"}], [{"description": "x", "unit_price": 1e12}], "x", [1]):
        assert client.put(f"/api/invoices/{inv['id']}", json={"items": bad}).status_code == 400
    preview = client.post("/api/invoices/preview", json={"items": [{"description": "a", "quantity": 3, "unit_price": 10},
                                                                   {"quantity": 1, "unit_price": "x"}],
                                                         "vat_rate": 0.2, "vat_exempt": False}).json()
    assert preview == {"subtotal": 30, "vat_amount": 6, "total": 36, "lines": [30, 0]}
    client.delete(f"/api/invoices/{inv['id']}")
    assert db.fetch_one("SELECT COUNT(*) AS n FROM invoice_lines WHERE invoice_id = ?", (inv["id"],))["n"] == 0


def test_public_invoice_lines(client):
    inv = next(i for i in services.list_invoices("invoice") if i["status"] == "paid")
    public = client.get(f"/api/public/invoices/{inv['public_token']}").json()["invoice"]
    assert public["items"] and set(public["items"][0]) == {"description", "quantity", "unit_price", "amount"}


# ═════════════════════════════════════════════════════════════════════════
# « Mes vues », automatisations et emails selon les droits
# ═════════════════════════════════════════════════════════════════════════
def test_views_hide_cards_of_forbidden_modules(client):
    make_member("vues@test.local", role_id("readonly"), {"accounting": 0})
    member = login_as("vues@test.local")
    spec = {"widgets": [{"source": "vat_by_month"}, {"source": "revenue_by_month"}, {"source": "kpi", "params": {"metric": "vat_balance"}}]}
    view = member.post("/api/dashboards/render", json={"spec": spec}).json()
    assert [w["source"] for w in view["widgets"]] == ["revenue_by_month"] and view["hidden"] == 2
    catalog = member.get("/api/dashboards").json()["catalog"]
    assert "vat_by_month" not in [c["source"] for c in catalog] and "revenue_by_month" in [c["source"] for c in catalog]
    composed = member.post("/api/dashboards/compose", json={"text": "ma TVA par mois"}).json()
    assert composed["view"]["widgets"] == [] and composed["view"]["hidden"] == 1


def test_automations_and_emails_follow_rights(client):
    make_member("auto@test.local", role_id("readonly"), {"accounting": 0})
    member = login_as("auto@test.local")
    jobs = [j["name"] for j in member.get("/api/automations").json()["jobs"]]
    assert "send_invoice" in jobs and "process_inbox" not in jobs
    assert member.post("/api/automations/auto_reminders/run").status_code == 403   # lecture seule
    assert member.post("/api/automations/process_inbox/run").status_code == 404
    runs = member.get("/api/automations/runs").json()
    assert runs and all(r["job"] != "process_inbox" for r in runs)
    kinds = {e["kind"] for e in member.get("/api/emails").json()}
    assert "invoice" in kinds and "alert" not in kinds
    alert = db.insert("emails", {"kind": "alert", "to_email": "a@b.c", "subject": "TVA", "html": "<p>x</p>",
                                 "status": "simulated", "created_at": db.now_iso()})
    assert member.get(f"/api/emails/{alert}/html").status_code == 404
    assert client.get(f"/api/emails/{alert}/html").status_code == 200


# ═════════════════════════════════════════════════════════════════════════
# Réinitialisation et mise à jour d'une instance existante
# ═════════════════════════════════════════════════════════════════════════
def test_reset_keeps_accounts_roles_and_modules(client, restore_modules):
    role = client.post("/api/settings/roles", json={"name": "Conservé"}).json()
    client.post("/api/data/sales/orders", json={"client_id": _client_id()})
    registry.set_enabled("accounting", False)
    assert client.post("/api/admin/reset", json={"mode": "empty"}).status_code == 200
    assert db.fetch_one("SELECT COUNT(*) AS n FROM sales_orders")["n"] == 0
    assert db.fetch_one("SELECT COUNT(*) AS n FROM invoice_lines")["n"] == 0
    assert permissions.get_role(role["id"])["name"] == "Conservé" and not registry.is_enabled("accounting")
    assert client.get("/api/auth/me").status_code == 200
    client.delete(f"/api/settings/roles/{role['id']}")


def test_upgrade_from_v3(tmp_path, monkeypatch):
    """Une instance d'avant les modules garde ses données et ses accès."""
    from caffein import config

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "v3.db")
    with sqlite3.connect(tmp_path / "v3.db") as conn:
        conn.executescript(f"{db.SCHEMA_V1}\n{db.SCHEMA_V2}\n{db.SCHEMA_V3}\nPRAGMA user_version = 3;")
        now = "2026-01-05T10:00:00+01:00"
        conn.execute("INSERT INTO users (email, password_hash, role, created_at) VALUES ('admin@x.fr', 'x', 'admin', ?)", (now,))
        conn.execute("INSERT INTO users (email, password_hash, role, created_at) VALUES ('membre@x.fr', 'x', 'member', ?)", (now,))
        conn.execute("INSERT INTO clients (name, created_at) VALUES ('Client', ?)", (now,))
        items = '[{"description": "Logo", "quantity": 2, "unit_price": 300}, {"description": "Charte", "quantity": 1, "unit_price": 150.5}]'
        conn.execute("""INSERT INTO invoices (kind, public_token, client_id, items, subtotal, vat_amount, total, status,
                        created_at, updated_at) VALUES ('invoice', 't1', 1, ?, 750.5, 150.1, 900.6, 'draft', ?, ?)""",
                     (items, now, now))
        conn.execute("""INSERT INTO invoices (kind, public_token, items, status, created_at, updated_at)
                        VALUES ('quote', 't2', 'pas du json', 'draft', ?, ?)""", (now, now))
    db.init_db()
    assert db.schema_version() == db.SCHEMA_VERSION
    inv = services.get_invoice(1)
    assert [(i["description"], i["quantity"], i["unit_price"]) for i in inv["items"]] == [("Logo", 2, 300), ("Charte", 1, 150.5)]
    assert inv["subtotal"] == 750.5 and services.get_invoice(2)["items"] == []
    member = auth.get_user_by_email("membre@x.fr")
    assert member["role_id"] == role_id("team") and auth.get_user_by_email("admin@x.fr")["role_id"] is None
    assert permissions.levels_for(auth.get_user(member["id"]))["sales"] == permissions.WRITE
    enabled = registry.enabled_keys()
    assert {"home", "sales", "accounting", "settings"} <= enabled
    new_modules = {k for k, m in registry.load().items() if not m.core and not m.upgrade_enabled}
    assert not (new_modules & enabled)  # les nouveaux modules arrivent désactivés
    db.init_db()  # rejouer les migrations ne change rien
    assert len(services.get_invoice(1)["items"]) == 2
