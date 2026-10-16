# SPDX-License-Identifier: AGPL-3.0-or-later
"""Données de démonstration des RH : l'équipe du Studio Durand, ses absences et ses notes de frais."""

from __future__ import annotations

from datetime import timedelta

from ... import db
from ...core import entities
from ...core.modules import MANAGE
from ...utils import add_months, today
from .workdays import next_working_day

DEPARTMENTS = [
    ("Direction", "Pilotage du studio, relation client et devis."),
    ("Création", "Identités visuelles, mises en page et maquettes."),
    ("Atelier", "Impression numérique, découpe et façonnage des kits de papeterie."),
    ("Administration", "Facturation, achats et suivi administratif."),
]

# (prénom, nom, service, poste, contrat, entrée il y a n mois, durée du contrat en mois, congés annuels,
#  salaire brut mensuel, email, notes)
EMPLOYEES = [
    ("Alex", "Durand", "Direction", "Gérant", "cdi", 110, None, 25, 4200, "alex@studio-durand.example", ""),
    ("Camille", "Roux", "Création", "Graphiste", "cdi", 62, None, 25, 2650, "camille.roux@studio-durand.example", ""),
    ("Hugo", "Martin", "Atelier", "Opérateur d'impression", "cdi", 38, None, 25, 2250,
     "hugo.martin@studio-durand.example", "Habilitation à la conduite du massicot."),
    ("Léa", "Bernard", "Administration", "Assistante de gestion", "cdd", 8, 12, 25, 2050,
     "lea.bernard@studio-durand.example", "CDD de douze mois pour accroissement temporaire d'activité."),
    ("Nina", "Lefèvre", "Création", "Stagiaire graphiste", "intern", 1, 6, 0, 700,
     "nina.lefevre@studio-durand.example", "Convention de stage de six mois ; gratification mensuelle."),
]
MANAGERS = {"Direction": "Alex Durand", "Création": "Camille Roux", "Atelier": "Hugo Martin", "Administration": "Alex Durand"}

# (salarié, objet, date de la note il y a n jours, statut visé, dépenses [(il y a n jours, catégorie, description, TTC, TVA)])
EXPENSES = [
    ("Camille Roux", "Salon de la papeterie à Paris", 6, "submitted", [
        (9, "transport", "Billet de train Lyon – Paris, aller-retour", 118.00, 10.73),
        (9, "lodging", "Hôtel, une nuit près du salon", 132.00, 12.00),
        (8, "meals", "Déjeuner sur le salon", 21.50, 1.95)]),
    ("Hugo Martin", "Livraison et fournitures de l'atelier", 2, "draft", [
        (3, "mileage", "Livraison à la Boulangerie Lemoine, 18 km aller-retour", 11.45, 0),
        (2, "supplies", "Lames de rechange pour le massicot", 38.90, 6.48)]),
    ("Alex Durand", "Rendez-vous client à Paris", 30, "paid", [
        (32, "transport", "Billet de train Lyon – Paris, aller-retour", 96.00, 8.73),
        (32, "meals", "Déjeuner de travail avec le client", 54.00, 4.91)]),
]


def seed_demo() -> None:
    def get(name: str) -> entities.Entity:
        return entities.get(f"hr.{name}")

    ref = today()
    departments = {name: entities.save_row(get("departments"), {"name": name, "description": text}, MANAGE)
                   for name, text in DEPARTMENTS}
    employees = {}
    for first, last, department, job, contract, months, duration, leave, salary, email, notes in EMPLOYEES:
        hired = add_months(ref.replace(day=1), -months)
        ended = add_months(hired, duration) - timedelta(days=1) if duration else None
        employees[f"{first} {last}"] = entities.save_row(get("employees"), {
            "first_name": first, "last_name": last, "department_id": departments[department], "job_title": job,
            "contract_type": contract, "hire_date": hired.isoformat(), "end_date": ended.isoformat() if ended else None,
            "annual_leave_days": leave, "salary": salary, "email": email, "notes": notes,
        }, MANAGE)
    for department, manager in MANAGERS.items():
        entities.save_row(get("departments"), {"manager_id": employees[manager]}, MANAGE, departments[department])

    # Absences : congés de Camille la semaine prochaine, arrêt maladie de Hugo la semaine dernière, RTT demandé par Léa
    absences = get("absences")
    monday = ref - timedelta(days=ref.weekday())
    rtt = next_working_day(ref + timedelta(days=10))
    for name, kind, start, end, status, reason in [
        ("Camille Roux", "paid_leave", monday + timedelta(days=7), monday + timedelta(days=11), "approved", "Vacances"),
        ("Hugo Martin", "sick", monday - timedelta(days=6), monday - timedelta(days=4), "approved", "Arrêt de travail"),
        ("Léa Bernard", "rtt", rtt, rtt, "requested", ""),
    ]:
        absence = entities.save_row(absences, {"employee_id": employees[name], "kind": kind, "start_date": start.isoformat(),
                                               "end_date": end.isoformat(), "reason": reason}, MANAGE)
        if status == "approved":
            entities.run_action(absences, absence, "approve", {}, {}, MANAGE)

    # Notes de frais : une à valider, un brouillon, une déjà remboursée (sans justificatif comptable de démonstration)
    expenses = get("expenses")
    for name, title, days_ago, status, lines in EXPENSES:
        expense = entities.save_row(expenses, {
            "employee_id": employees[name], "title": title, "date": (ref - timedelta(days=days_ago)).isoformat(),
            "lines": [{"date": (ref - timedelta(days=ago)).isoformat(), "category": category, "description": text,
                       "amount": amount, "vat": vat} for ago, category, text, amount, vat in lines],
        }, MANAGE)
        if status in ("submitted", "paid"):
            entities.run_action(expenses, expense, "submit", {}, {}, MANAGE)
        if status == "paid":
            entities.run_action(expenses, expense, "approve", {}, {}, MANAGE)
            db.execute("UPDATE hr_expenses SET status = 'paid', paid_on = ?, updated_at = ? WHERE id = ?",
                       ((ref - timedelta(days=days_ago - 10)).isoformat(), db.now_iso(), expense))
