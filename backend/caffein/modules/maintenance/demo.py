# SPDX-License-Identifier: AGPL-3.0-or-later
"""Données de démonstration de la Maintenance : les trois machines de l'atelier du Studio Durand.

L'imprimante a eu sa maintenance trimestrielle il y a 80 jours (la prochaine tombe dans 10 jours), le massicot est en
réparation (lame émoussée) et l'entretien annuel de la plastifieuse est planifié la semaine prochaine. Les postes de
charge et le technicien sont repris des autres modules s'ils sont actifs et que la fiche existe ; rien n'y est créé."""

from __future__ import annotations

from datetime import timedelta

from ... import db
from ...core import entities
from ...core import modules as registry
from ...core.modules import MANAGE
from ...utils import today

# (nom, poste de charge, périodicité en jours, achat il y a … jours, emplacement, fabricant, modèle, n° de série, notes)
EQUIPMENT = [
    ("Imprimante numérique", "Imprimante numérique", 90, 1100, "Atelier, rez-de-chaussée", "Lumia Print", "LP 6100",
     "LP61-0042718", "Contrat d'entretien : nettoyage des têtes et étalonnage tous les trois mois."),
    ("Massicot", "Massicot", 180, 2200, "Atelier, rez-de-chaussée", "Coupex", "C-520", "CX520-11873",
     "Lame de rechange en stock à l'atelier. Conduite réservée aux personnes habilitées."),
    ("Plastifieuse", "Atelier de façonnage", 365, 358, "Atelier, poste de façonnage", "Lamitec", "L-380", "LT380-2291",
     "Entretien annuel : rouleaux, résistances et réglage de la température."),
]

# (équipement, type, intitulé, prévue il y a … jours, statut visé, durée (h), coût, compte rendu)
INTERVENTIONS = [
    ("Imprimante numérique", "preventive", "Maintenance trimestrielle : nettoyage des têtes et étalonnage", 80, "done",
     2, 180, "Têtes nettoyées, étalonnage des couleurs refait sur le papier couché 350 g."),
    ("Massicot", "preventive", "Graissage et contrôle des sécurités", 120, "done", 1.5, 95,
     "Graissage du chariot, barrière immatérielle et double commande contrôlées."),
    ("Massicot", "corrective", "Lame émoussée", 1, "in_progress", None, None,
     "La lame accroche le papier et la coupe se décale : affûtage ou remplacement de la lame."),
]


def _day(offset: int) -> str:
    return (today() + timedelta(days=offset)).isoformat()


def seed_demo() -> None:
    equipment, interventions = entities.get("maintenance.equipment"), entities.get("maintenance.interventions")
    workcenters = {}
    if registry.is_enabled("technical"):
        workcenters = {r["name"]: r["id"] for r in db.fetch_all("SELECT id, name FROM technical_workcenters")}
    technician = None
    if registry.is_enabled("hr"):
        row = db.fetch_one("SELECT id FROM hr_employees WHERE full_name = 'Hugo Martin'")
        technician = row["id"] if row else None

    ids = {}
    for name, workcenter, interval, bought, location, maker, model, serial, notes in EQUIPMENT:
        ids[name] = entities.save_row(equipment, {
            "name": name, "workcenter_id": workcenters.get(workcenter), "interval_days": interval,
            "purchase_date": _day(-bought), "location": location, "manufacturer": maker, "model": model,
            "serial_number": serial, "notes": notes}, MANAGE)

    for name, kind, title, planned, status, hours, cost, report in INTERVENTIONS:
        job = entities.save_row(interventions, {
            "equipment_id": ids[name], "kind": kind, "title": title, "planned_date": _day(-planned),
            "technician_id": technician, "duration_hours": hours, "cost": cost, "report": report}, MANAGE)
        if status == "in_progress":
            entities.run_action(interventions, job, "start", {}, {}, MANAGE)
        if status == "done":  # terminée le jour prévu
            entities.run_action(interventions, job, "done", {"date": _day(-planned)}, {}, MANAGE)
    # La réparation du massicot est en cours, mais la machine coupe encore : elle reste utilisable, en mode dégradé
    entities.save_row(equipment, {"status": "degraded"}, MANAGE, ids["Massicot"])

    # Entretien annuel de la plastifieuse : planifié à sa date d'échéance, la semaine prochaine
    entities.run_action(equipment, ids["Plastifieuse"], "schedule", {}, {}, MANAGE)
    planned = db.fetch_one("SELECT id FROM maintenance_interventions WHERE equipment_id = ? AND status = 'planned'",
                           (ids["Plastifieuse"],))
    entities.save_row(interventions, {"technician_id": technician, "duration_hours": 1}, MANAGE, planned["id"])
