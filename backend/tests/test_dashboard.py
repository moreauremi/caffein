# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tableau de bord à la demande (« Mes vues ») : validation, analyse locale, données, API et isolement des vues."""

import pytest

from caffein import auth, dashboard, services


def sources(spec: dict) -> list[str]:
    return [w["source"] for w in spec["widgets"]]


# ── Validation : rien d'inconnu ne passe ─────────────────────────────────
def test_validate_spec_drops_unknown_and_caps():
    spec = dashboard.validate_spec({
        "title": "  Ma   vue  ",
        "widgets": [
            {"source": "revenue_by_month", "visual": "pie", "params": {"period": "decade", "sql": "DROP TABLE invoices"}},
            {"source": "DROP TABLE invoices"},
            "pas un objet",
            {"source": "kpi", "params": {"metric": "secret"}},
            {"source": "revenue_by_month", "visual": "bar", "params": {"period": "last_12_months"}},  # doublon
            {"source": "unpaid_invoices", "params": {"limit": 999, "only_overdue": "oui"}},
        ] + [{"source": "kpi", "params": {"metric": m}} for m in dashboard.METRICS],
    })
    assert spec["title"] == "Ma vue"
    first = spec["widgets"][0]
    assert first == {"source": "revenue_by_month", "visual": "bar", "title": "", "params": {"period": "last_12_months"}}
    assert spec["widgets"][1]["params"] == {"metric": "to_collect"}
    assert spec["widgets"][2]["params"] == {"limit": 20, "only_overdue": False}
    assert len(spec["widgets"]) == dashboard.MAX_WIDGETS
    assert dashboard.validate_spec(None) == {"title": "", "widgets": []}
    assert dashboard.validate_spec({"widgets": "tout"}) == {"title": "", "widgets": []}


# ── Analyse locale (sans IA) ─────────────────────────────────────────────
def test_offline_compose_add_remove():
    res = dashboard.compose_offline("Montre-moi mon chiffre d'affaires par mois et mes factures impayées", {})
    assert res["message"] == "composed" and sources(res["spec"]) == ["revenue_by_month", "unpaid_invoices"]

    res = dashboard.compose_offline("Ajoute mes dépenses par catégorie sur l'année", res["spec"])
    assert res["message"] == "added"
    assert sources(res["spec"]) == ["revenue_by_month", "unpaid_invoices", "expenses_by_category"]
    assert res["spec"]["widgets"][2]["params"] == {"period": "year"}

    res = dashboard.compose_offline("Enlève les impayés", res["spec"])
    assert res["message"] == "removed" and sources(res["spec"]) == ["revenue_by_month", "expenses_by_category"]

    res = dashboard.compose_offline("ajoute aussi le top 5 de mes clients en tableau", res["spec"])
    client = res["spec"]["widgets"][-1]
    assert client["source"] == "revenue_by_client" and client["visual"] == "table" and client["params"]["limit"] == 5

    assert dashboard.compose_offline("efface tout", res["spec"])["spec"]["widgets"] == []


@pytest.mark.parametrize("text, expected", [
    ("Mes factures en retard et la TVA du trimestre", ["unpaid_invoices", "vat_by_month"]),
    ("Quels sont mes plus gros clients cette année ?", ["revenue_by_client"]),
    ("show my unpaid invoices and monthly revenue", ["unpaid_invoices", "revenue_by_month"]),
    ("combien j'ai encaissé ce mois-ci et le temps gagné", ["kpi", "kpi"]),
    ("mes devis en attente et les prochaines échéances", ["pending_quotes", "deadlines"]),
])
def test_offline_compose_phrasings(text, expected):
    assert sources(dashboard.compose_offline(text, {})["spec"]) == expected


def test_offline_compose_details():
    overdue = dashboard.compose_offline("mes factures en retard", {})["spec"]["widgets"][0]
    assert overdue["params"]["only_overdue"] is True
    six = dashboard.compose_offline("mon CA sur les 6 derniers mois", {})["spec"]["widgets"][0]
    assert six["params"]["period"] == "last_6_months"
    # « ça » n'est pas « CA »
    assert dashboard.compose_offline("montre-moi ça", {})["message"] == "not_understood"


@pytest.mark.parametrize("text", [
    "change l'échéance de la facture 14 au 30",
    "supprime la facture 12",
    "relance Atelier Nova",
    "marque la facture 3 comme payée",
])
def test_offline_compose_refuses_modifications(text):
    current = dashboard.compose_offline("mon chiffre d'affaires", {})["spec"]
    res = dashboard.compose_offline(text, current)
    assert res["message"] == "read_only" and res["understood"] is False and res["spec"] == current


# ── Données : chaque source se calcule sur la démo ────────────────────────
def test_render_every_source(demo):
    spec = {"widgets": [{"source": s} for s in dashboard.SOURCES]}
    view = dashboard.render(spec)
    data = {w["source"]: w["data"] for w in view["widgets"]}
    assert set(data) == set(dashboard.SOURCES)
    assert data["kpi"]["value"] > 0 and data["kpi"]["unit"] == "money"
    assert len(data["revenue_by_month"]["rows"]) == 12 and sum(r["paid"] for r in data["revenue_by_month"]["rows"]) > 0
    clients = data["revenue_by_client"]["rows"]
    assert clients and clients == sorted(clients, key=lambda r: -r["amount"])
    unpaid = data["unpaid_invoices"]
    assert unpaid["count"] > 0 and unpaid["rows"][0]["days_overdue"] >= unpaid["rows"][-1]["days_overdue"]
    assert data["expenses_by_category"]["rows"]
    assert data["vat_by_month"]["series"] == ["collected", "deductible"]
    assert data["deadlines"]["rows"]


def test_kpis_match_existing_dashboards(demo):
    summary = services.invoice_summary()
    view = dashboard.render({"widgets": [{"source": "kpi", "params": {"metric": m}} for m in ("to_collect", "overdue_total")]})
    assert [w["data"]["value"] for w in view["widgets"]] == [summary["to_collect"], summary["overdue_total"]]


# ── API ──────────────────────────────────────────────────────────────────
def test_api_compose_save_reload_delete(client):
    res = client.post("/api/dashboards/compose", json={"text": "mon chiffre d'affaires par mois et mes impayés"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["composed_by"] == "heuristique" and body["understood"] and body["message"] == "composed"
    spec = {"title": body["view"]["title"], "widgets": [{k: w[k] for k in ("source", "visual", "title", "params")}
                                                         for w in body["view"]["widgets"]]}
    assert all("data" in w for w in body["view"]["widgets"])

    added = client.post("/api/dashboards/compose", json={"text": "ajoute la TVA", "spec": spec}).json()
    assert [w["source"] for w in added["view"]["widgets"]][-1] == "vat_by_month"

    saved = client.post("/api/dashboards", json={"name": "Pilotage", "spec": spec, "prompt": "mon CA"})
    assert saved.status_code == 201
    view_id = saved.json()["id"]
    listing = client.get("/api/dashboards").json()
    assert [v["name"] for v in listing["views"]] == ["Pilotage"] and listing["catalog"] and listing["ai"]["mode"] == "offline"

    loaded = client.get(f"/api/dashboards/{view_id}").json()
    assert [w["source"] for w in loaded["view"]["widgets"]] == ["revenue_by_month", "unpaid_invoices"]
    assert client.put(f"/api/dashboards/{view_id}", json={"name": "Pilotage mensuel"}).json()["name"] == "Pilotage mensuel"

    rendered = client.post("/api/dashboards/render", json={"spec": spec}).json()
    assert len(rendered["widgets"]) == 2

    assert client.delete(f"/api/dashboards/{view_id}").status_code == 204
    assert client.get(f"/api/dashboards/{view_id}").status_code == 404


def test_api_validates_input(client):
    assert client.post("/api/dashboards/compose", json={"text": ""}).status_code == 400
    assert client.post("/api/dashboards/compose", json={"text": "x" * 501}).status_code == 400
    assert client.post("/api/dashboards", json={"name": "", "spec": {"widgets": [{"source": "kpi"}]}}).status_code == 400
    assert client.post("/api/dashboards", json={"name": "Vide", "spec": {"widgets": [{"source": "inconnue"}]}}).status_code == 400
    refused = client.post("/api/dashboards/compose", json={"text": "supprime la facture 3"}).json()
    assert refused["understood"] is False and refused["message"] == "read_only"


def test_api_requires_login(anon):
    assert anon.post("/api/dashboards/compose", json={"text": "mon CA"}).status_code == 401
    assert anon.get("/api/dashboards").status_code == 401


def test_views_are_private(client):
    view_id = client.post("/api/dashboards", json={"name": "À moi", "spec": {"widgets": [{"source": "deadlines"}]}}).json()["id"]
    member = auth.get_user_by_email("membre@test.local") or auth.create_user(
        "membre@test.local", "motdepasse-membre", "Membre", "member")
    other = dashboard.list_views(member["id"])
    assert all(v["id"] != view_id for v in other)
    with pytest.raises(services.NotFound):
        dashboard.get_view(member["id"], view_id)
    with pytest.raises(services.NotFound):
        dashboard.delete_view(member["id"], view_id)
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"email": "membre@test.local", "password": "motdepasse-membre"}).status_code == 200
    assert client.get(f"/api/dashboards/{view_id}").status_code == 404
    assert client.delete(f"/api/dashboards/{view_id}").status_code == 404


# ── Avec Claude (appel simulé) : la sortie passe quand même par la validation ──
def test_compose_with_ai_is_validated(client, monkeypatch):
    from caffein import ai, config

    calls = []

    def fake_json_call(system, content, schema, max_tokens=8000):
        calls.append((system, content, schema))
        return {"understood": True, "reply": "J'affiche ton CA.", "title": "",
                "widgets": [{"source": "revenue_by_month", "visual": "bar", "title": "CA",
                             "params": {"metric": None, "period": "last_6_months", "limit": None, "only_overdue": None}},
                            {"source": "rm -rf", "visual": "bar", "title": "x", "params": {}}]}

    monkeypatch.setattr(config, "AI_ENABLED", True)
    monkeypatch.setattr(ai, "_json_call", fake_json_call)
    body = client.post("/api/dashboards/compose", json={"text": "mon CA sur 6 mois"}).json()
    assert body["composed_by"] == "claude" and body["reply"] == "J'affiche ton CA."
    assert [(w["source"], w["params"]["period"]) for w in body["view"]["widgets"]] == [("revenue_by_month", "last_6_months")]

    # L'IA ne reçoit que la demande, le catalogue et la vue : aucune donnée de l'entreprise
    system, content, schema = calls[0]
    assert content.endswith("<demande>mon CA sur 6 mois</demande>") and content.startswith("<vue_actuelle>")
    assert "Atelier Nova" not in system + content and "CAFFEIN-2026" not in system + content
    assert schema["properties"]["widgets"]["items"]["properties"]["source"]["enum"] == list(dashboard.SOURCES)


def test_compose_with_ai_refusal_keeps_view(client, monkeypatch):
    from caffein import ai, config

    monkeypatch.setattr(config, "AI_ENABLED", True)
    monkeypatch.setattr(ai, "_json_call", lambda *a, **k: {
        "understood": False, "reply": "Cette page ne fait qu'afficher.", "title": "", "widgets": []})
    current = {"widgets": [{"source": "deadlines"}]}
    body = client.post("/api/dashboards/compose", json={"text": "supprime la facture 3", "spec": current}).json()
    assert body["understood"] is False and [w["source"] for w in body["view"]["widgets"]] == ["deadlines"]


def test_compose_falls_back_offline_when_ai_fails(client, monkeypatch):
    from caffein import ai, config

    def broken(*_a, **_k):
        raise ai.AIUnavailable("API Anthropic injoignable")

    monkeypatch.setattr(config, "AI_ENABLED", True)
    monkeypatch.setattr(ai, "_json_call", broken)
    body = client.post("/api/dashboards/compose", json={"text": "mes devis en attente"}).json()
    assert body["composed_by"] == "heuristique" and [w["source"] for w in body["view"]["widgets"]] == ["pending_quotes"]



# ── Corrections de la relecture ──────────────────────────────────────────
def test_validate_spec_survives_crafted_values():
    spec = dashboard.validate_spec({"title": {"x": 1}, "widgets": [
        {"source": ["kpi"]}, {"source": {"x": 1}}, {"source": None},
        {"source": "unpaid_invoices", "title": ["x"], "params": {"limit": float("inf")}},
        {"source": "pending_quotes", "params": {"limit": True}},
    ] + [{"source": "deadlines"}] * 100_000})
    assert [w["source"] for w in spec["widgets"]] == ["unpaid_invoices", "pending_quotes", "deadlines"]
    assert spec["title"] == "" and spec["widgets"][0]["title"] == "" and spec["widgets"][0]["params"]["limit"] == 8
    assert spec["widgets"][1]["params"]["limit"] == 8


def test_api_rejects_nothing_with_500(client):
    for raw in ('{"spec": {"widgets": [{"source": ["kpi"]}]}}',
                '{"spec": {"widgets": [{"source": "unpaid_invoices", "params": {"limit": 1e999}}]}}',
                '{"spec": {"widgets": [{"source": "unpaid_invoices", "params": {"limit": Infinity}}]}}'):
        for path in ("/api/dashboards/render", "/api/dashboards/compose"):
            body = raw if path.endswith("render") else raw[:-1] + ', "text": "mes devis"}'
            res = client.post(path, content=body, headers={"Content-Type": "application/json"})
            assert res.status_code == 200, (path, raw, res.text)
    res = client.post("/api/dashboards", content='{"name": "x", "spec": {"widgets": [{"source": ["kpi"]}]}}',
                      headers={"Content-Type": "application/json"})
    assert res.status_code == 400


@pytest.mark.parametrize("text", [
    "supprime la facture CAFFEIN-2026-00004",
    "supprime la facture n° CAFFEIN-2026-00004",
    "supprime le devis DEVIS-2026-00002",
    "supprime la facture de Kairos",
    "pourrais-tu supprimer la facture 2026-00004",
    "change le client de la facture 3",
    "envoie la facture à Atelier Nova",
    "crée une facture pour Atelier Nova",
])
def test_offline_refuses_real_records(text):
    current = dashboard.compose_offline("mon chiffre d'affaires et mes impayés", {})["spec"]
    res = dashboard.compose_offline(text, current)
    assert res["message"] == "read_only" and res["spec"] == current


@pytest.mark.parametrize("text, expected", [
    ("Montre-moi mes factures 2026", ["revenue_by_month"]),
    ("Mon CA par client 2025", ["revenue_by_client"]),
    ("mes devis 2026", ["pending_quotes"]),
    ("Crée une vue avec mon CA", ["revenue_by_month"]),
    ("Change la vue pour afficher mes dépenses", ["expenses_by_category"]),
    ("Mets à jour la vue avec la TVA", ["vat_by_month"]),
])
def test_offline_does_not_refuse_display_requests(text, expected):
    res = dashboard.compose_offline(text, {})
    assert res["understood"] and sources(res["spec"]) == expected, res


def test_offline_switch_clear_and_remove():
    view = dashboard.compose_offline("mon CA, mes impayés et mes dépenses", {})["spec"]
    assert sources(view) == ["revenue_by_month", "unpaid_invoices", "expenses_by_category"]
    res = dashboard.compose_offline("Modifie le graphique en tableau", view)
    assert res["message"] == "changed" and {w["visual"] for w in res["spec"]["widgets"]} == {"table"}
    res = dashboard.compose_offline("passe les dépenses en graphique", res["spec"])
    assert [w["visual"] for w in res["spec"]["widgets"]] == ["table", "table", "bar"]
    res = dashboard.compose_offline("efface le CA", view)
    assert res["message"] == "removed" and sources(res["spec"]) == ["unpaid_invoices", "expenses_by_category"]
    assert dashboard.compose_offline("vide les impayés", view)["message"] == "removed"
    assert dashboard.compose_offline("enlève tout", view)["spec"]["widgets"] == []


@pytest.mark.parametrize("text, expected", [
    ("calculate my revenue", [("revenue_by_month", None)]),
    ("show my latest revenue", [("revenue_by_month", None)]),
    ("Mes dépenses ce mois-ci", [("expenses_by_category", None)]),
    ("Revenue by customer", [("revenue_by_client", None)]),
    ("My top customers", [("revenue_by_client", None)]),
    ("How much do I have left to collect?", [("kpi", "to_collect")]),
    ("Quel est mon solde de TVA ?", [("kpi", "vat_balance")]),
    ("Mon CA de l'année", [("kpi", "revenue_year")]),
    ("Mes encaissements du mois", [("kpi", "paid_month")]),
    ("le total en retard", [("kpi", "overdue_total")]),
    ("combien de devis en attente", [("kpi", "quotes_pending")]),
])
def test_offline_more_phrasings(text, expected):
    widgets = dashboard.compose_offline(text, {})["spec"]["widgets"]
    assert [(w["source"], w["params"].get("metric")) for w in widgets] == expected


def test_offline_periods_and_limits():
    assert dashboard.compose_offline("comment ca va", {})["message"] == "not_understood"
    for text in ("Mon CA de l'année dernière", "Revenue last year", "Sales last quarter", "mes dépenses du mois dernier"):
        assert dashboard.compose_offline(text, {})["message"] == "period_unsupported", text
    client = dashboard.compose_offline("Mon chiffre d'affaires par client sur les 6 derniers mois", {})["spec"]["widgets"][0]
    assert client["params"] == {"period": "last_6_months", "limit": 8}
    assert dashboard.compose_offline("mes 3 meilleurs clients", {})["spec"]["widgets"][0]["params"]["limit"] == 3
    default = dashboard.compose_offline("show me an overview of my sales", {})["spec"]["widgets"][0]
    assert default["params"]["period"] == "last_12_months"


def test_ranges_on_fixed_dates():
    from datetime import date

    assert dashboard._range("quarter", date(2026, 10, 14)) == (date(2026, 10, 1), date(2026, 12, 31))
    assert dashboard._range("quarter", date(2027, 1, 10)) == (date(2027, 1, 1), date(2027, 3, 31))
    assert dashboard._range("year", date(2026, 12, 31)) == (date(2026, 1, 1), date(2026, 12, 31))
    assert dashboard._range("last_6_months", date(2027, 1, 10)) == (date(2026, 8, 1), date(2027, 1, 31))
    months = dashboard._months("last_12_months", date(2027, 1, 10))
    assert len(months) == 12 and months[0] == date(2026, 2, 1) and months[-1] == date(2027, 1, 1)


def test_kpis_match_other_pages(demo):
    from caffein import services

    view = dashboard.render({"widgets": [{"source": "kpi", "params": {"metric": m}} for m in dashboard.METRICS]})
    values = {w["params"]["metric"]: w["data"]["value"] for w in view["widgets"]}
    summary = services.invoice_summary()
    assert values["paid_month"] == summary["paid_month"] and values["quotes_pending"] == summary["quotes_pending"]
    assert values["time_saved"] == services.time_saved_minutes()
    assert values["vat_balance"] == services.home_dashboard()["stats"]["balance"]
    assert values["revenue_year"] == services.urssaf_dashboard()["ca_year"]


def test_clients_with_same_name_stay_separate(demo):
    from caffein import db

    db.execute("UPDATE clients SET name = 'Martin' WHERE name IN ('Atelier Nova', 'Kairos Conseil')")
    rows = dashboard.render({"widgets": [{"source": "revenue_by_client", "params": {"limit": 20}}]})["widgets"][0]["data"]["rows"]
    labels = [r["label"] for r in rows]
    assert labels.count("Martin") == 1 and "Martin (2)" in labels


def test_vat_cards_flag_exemption(demo):
    from caffein import services

    services.update_profile({"vat_exempt": True})
    view = dashboard.render({"widgets": [{"source": "kpi", "params": {"metric": "vat_balance"}}, {"source": "vat_by_month"}]})
    assert all(w["data"]["vat_exempt"] for w in view["widgets"])


def test_saved_views_limit_is_enforced(demo):
    from caffein import db

    db.execute("DELETE FROM dashboard_views WHERE user_id = ?", (demo["id"],))
    spec = {"widgets": [{"source": "deadlines"}]}
    for i in range(dashboard.MAX_VIEWS):
        dashboard.create_view(demo["id"], {"name": f"Vue {i}", "spec": spec})
    with pytest.raises(services.Conflict):
        dashboard.create_view(demo["id"], {"name": "De trop", "spec": spec})
    db.execute("DELETE FROM dashboard_views WHERE user_id = ?", (demo["id"],))


def test_migration_from_v2(tmp_path, monkeypatch):
    import sqlite3

    from caffein import config, db

    monkeypatch.setattr(config, "DB_PATH", tmp_path / "v2.db")
    with sqlite3.connect(tmp_path / "v2.db") as conn:
        conn.executescript(f"{db.SCHEMA_V1}\n{db.SCHEMA_V2}\nPRAGMA user_version = 2;")
    db.init_db()
    assert db.schema_version() == 3
    assert db.fetch_all("SELECT * FROM dashboard_views") == []


def test_ai_quota_falls_back_offline(client, monkeypatch):
    from caffein import ai, config

    calls = []
    monkeypatch.setattr(config, "AI_ENABLED", True)
    monkeypatch.setattr(ai, "_json_call", lambda *a, **k: calls.append(1) or {
        "understood": True, "reply": "", "title": "", "widgets": [{"source": "deadlines", "visual": "list", "title": "",
                                                                   "params": {"metric": None, "period": None, "limit": None, "only_overdue": None}}]})
    monkeypatch.setattr(dashboard, "_ai_calls", {})
    bodies = [client.post("/api/dashboards/compose", json={"text": "mes devis en attente"}).json()
              for _ in range(dashboard.AI_CALLS_PER_MINUTE + 2)]
    assert len(calls) == dashboard.AI_CALLS_PER_MINUTE
    assert bodies[0]["composed_by"] == "claude" and bodies[0]["message"] == "composed" and bodies[0]["reply"] is None
    assert bodies[-1]["composed_by"] == "heuristique"
