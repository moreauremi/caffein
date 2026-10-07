# SPDX-License-Identifier: AGPL-3.0-or-later
from datetime import date

from caffein import ai, crypto, fiscal, services
from caffein.jobs import run_job
from caffein.jobs.auto_reminders import choose_tone
from caffein.utils import fmt_money, to_float


def test_money_and_numbers():
    assert fmt_money(1234.5) == "1 234,50 €"
    assert fmt_money(-3) == "-3,00 €"
    assert to_float("1 234,56 €") == 1234.56
    assert to_float("1.234,56") == 1234.56
    assert to_float("1,234.56") == 1234.56
    assert to_float("abc") is None


def test_encryption_roundtrip():
    token = crypto.encrypt(1234.5)
    assert token.startswith("v1:") and "1234" not in token
    assert crypto.decrypt(token) == "1234.5"
    assert crypto.decrypt("valeur en clair") == "valeur en clair"
    assert crypto.decrypt("") == ""


def test_tva_periods_and_deadline():
    ref = date(2026, 10, 7)
    month = fiscal.tva_period("month", ref)
    assert (month.start, month.end) == (date(2026, 10, 1), date(2026, 10, 31))
    quarter = fiscal.tva_period("quarter", ref)
    assert quarter.start == date(2026, 8, 1)
    assert fiscal.tva_deadline(month.end) == date(2026, 11, 20)
    assert len(fiscal.tva_chart_months("year", ref)) == 12


def test_urssaf_quarterly_deadlines():
    periods = fiscal.declaration_periods(2026, "quarterly")
    assert [fiscal.declaration_deadline(p) for p in periods] == [
        date(2026, 4, 30), date(2026, 7, 31), date(2026, 10, 31), date(2027, 1, 31)]
    monthly = fiscal.declaration_periods(2026, "monthly")
    assert fiscal.declaration_deadline(monthly[1]) == date(2026, 3, 31)


def test_reminder_tone_escalation():
    assert choose_tone(0, 3) == "gentle"
    assert choose_tone(0, 15) == "firm"
    assert choose_tone(1, 10) == "firm"
    assert choose_tone(1, 30) == "final"
    assert choose_tone(2, 10) == "final"


def test_natural_language_offline():
    clients = [{"id": 1, "name": "Atelier Nova", "contact_name": "Jean Martin"}]
    r = ai.parse_invoice_request_offline("Mission logo pour Jean Martin, 800 EUR, livraison le 15", clients, date(2026, 10, 7))
    assert r["existing_client_id"] == 1
    assert r["items"] == [{"description": "Mission logo", "quantity": 1, "unit_price": 800.0}]
    assert r["delivery_date"] == "2026-10-15"
    r = ai.parse_invoice_request_offline("Devis : 3 jours à 450 € de formation Figma pour Kairos", [], date(2026, 10, 20))
    assert r["kind"] == "quote"
    assert r["items"][0]["quantity"] == 3 and r["items"][0]["unit_price"] == 450


def test_invoice_lifecycle(demo):
    client = services.create_client({"name": "Test SARL", "email": "test@example.com"})
    inv = services.create_invoice({"client_id": client["id"], "title": "Audit",
                                   "items": [{"description": "Audit", "quantity": 2, "unit_price": 500}]})
    assert inv["status"] == "draft" and inv["total"] == 1200.0  # TVA 20 % (profil démo assujetti)

    inv = services.finalize_invoice(inv["id"])
    assert inv["status"] == "pending" and inv["number"].startswith("CAFFEIN-") and inv["has_pdf"]

    paid = services.mark_paid(inv["id"], "2026-10-07")
    assert paid["status"] == "paid"
    docs = [d for d in services.list_documents() if d["invoice_id"] == inv["id"]]
    assert len(docs) == 1 and docs[0]["tva_type"] == "collected" and docs[0]["tva"] == 200.0


def test_numbering_is_sequential(demo):
    client = services.create_client({"name": "Seq"})
    numbers = []
    for _ in range(2):
        inv = services.create_invoice({"client_id": client["id"], "items": [{"description": "x", "quantity": 1, "unit_price": 10}]})
        numbers.append(services.finalize_invoice(inv["id"])["number"])
    a, b = (int(n.rsplit("-", 1)[1]) for n in numbers)
    assert b == a + 1


def test_inbox_processing_offline(demo):
    result = run_job("process_inbox", trigger="test")
    assert result["status"] == "success"
    assert result["details"]["processed"] == 2
    suppliers = {r["fournisseur"] for r in result["details"]["results"]}
    assert suppliers == {"FREE PRO", "CANVA PTY LTD"}
    assert services.inbox_files() == []


def test_reminders_job_sends_due_reminders(demo):
    result = run_job("auto_reminders", trigger="test")
    assert result["status"] == "success"
    sent = result["details"]["sent"]
    assert {s["tone"] for s in sent} <= {"gentle", "firm", "final"} and len(sent) == 2
    again = run_job("auto_reminders", trigger="schedule")  # intervalle de 7 jours respecté
    assert again["id"] is None


def test_newsletter_to_notification_keeps_four(demo):
    run_job("newsletter_notifications", trigger="test",
            text="Objet : Newsletter — Nouveau : export comptable\n\nDécouvrez le nouvel export FEC disponible dès aujourd'hui.")
    notes = services.list_notifications()
    assert len(notes) == 4
    assert notes[0]["tag"] == "📮 Nouveauté"


def test_onboarding_sequence(demo):
    first = run_job("onboarding_emails", trigger="test")
    assert "envoyé" in first["summary"]
    assert services.get_profile()["onboarding_done"]  # le profil démo a déjà des factures → félicitations


def test_urssaf_dashboard(demo):
    data = services.urssaf_dashboard()
    assert data["ca_year"] > 0
    assert abs(data["contributions_year"] - data["ca_year"] * data["activity"]["total_rate"]) < 0.05
    assert any(p["status"] == "to_declare" for p in data["periods"])
