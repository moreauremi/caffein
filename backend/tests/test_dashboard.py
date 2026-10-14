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
    assert content == "mon CA sur 6 mois"
    assert "Atelier Nova" not in system and "CAFFEIN-2026" not in system
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
