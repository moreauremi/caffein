# SPDX-License-Identifier: AGPL-3.0-or-later
def test_dashboards(client):
    assert client.get("/api/config").json()["ai"]["mode"] == "offline"
    home = client.get("/api/home").json()
    kpis = {k["key"]: k for k in home["kpis"]}
    assert kpis["accounting.documents"]["value"] > 0 and len(home["notifications"]) == 4
    assert kpis["sales.to_collect"]["unit"] == "money" and home["next_deadlines"]
    for period in ("month", "quarter", "year"):
        tva = client.get(f"/api/tva?period={period}").json()
        assert "balance" in tva["metrics"] and tva["chart"]
    assert client.get("/api/urssaf").json()["periods"]


def test_assistant_creates_draft_and_send_flow(client):
    res = client.post("/api/invoices/assistant", json={"text": "Mission logo pour Jean Martin, 800 EUR, livraison le 15"})
    assert res.status_code == 201
    inv = res.json()["invoice"]
    assert inv["status"] == "draft" and inv["client_name"] == "Atelier Nova" and inv["subtotal"] == 800

    pdf = client.get(f"/api/invoices/{inv['id']}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    sent = client.post(f"/api/invoices/{inv['id']}/send", json={}).json()
    assert sent["run"]["status"] == "success" and sent["invoice"]["status"] == "pending"
    assert sent["invoice"]["emailed_to"] == "jean.martin@atelier-nova.example"

    public = client.get(f"/api/public/invoices/{sent['invoice']['public_token']}").json()
    assert public["invoice"]["number"] == sent["invoice"]["number"]

    assert client.put(f"/api/invoices/{inv['id']}", json={"title": "x"}).status_code == 409
    assert client.delete(f"/api/invoices/{inv['id']}").status_code == 409


def test_upload_document(client, tmp_path):
    from caffein.pdf_invoice import render_supplier_invoice_pdf

    pdf = render_supplier_invoice_pdf({"company": "Imprimerie Test", "address": "1 rue", "city": "75001 Paris"},
                                      {"name": "Studio Durand"}, "T-1", "2026-10-01", "2026-10-31",
                                      [("Impression cartes de visite", 1, 50)], 0.2)
    res = client.post("/api/documents/upload", files={"files": ("cartes.pdf", pdf, "application/pdf")})
    run = res.json()["run"]
    assert run["status"] == "success", run
    result = run["details"]["results"][0]
    assert result["fournisseur"] == "IMPRIMERIE TEST" and result["ttc"] == 60.0 and result["categorie"] == "Marketing"


def test_quote_conversion(client):
    quotes = client.get("/api/invoices?kind=quote").json()
    accepted = next(q for q in quotes if q["status"] == "accepted")
    invoice = client.post(f"/api/invoices/{accepted['id']}/convert").json()
    assert invoice["kind"] == "invoice" and invoice["status"] == "draft"
    assert client.get(f"/api/invoices/{accepted['id']}").json()["status"] == "invoiced"


def test_folder_traversal_is_blocked(client):
    assert client.get("/api/folders/recues/file", params={"path": "../../../caffein.db"}).status_code == 404


def test_email_preview_has_csp(client):
    emails = client.get("/api/emails").json()
    res = client.get(f"/api/emails/{emails[0]['id']}/html")
    assert res.status_code == 200 and "default-src 'none'" in res.headers["content-security-policy"]
