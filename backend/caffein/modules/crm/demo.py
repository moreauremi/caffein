# SPDX-License-Identifier: AGPL-3.0-or-later
"""Données de démonstration du CRM : les prospects du Studio Durand, ses opportunités (avec les clients existants
des Ventes, sans créer ni client ni devis) et ses actions commerciales de la semaine."""

from __future__ import annotations

from datetime import timedelta

from ... import db
from ...core import entities
from ...core import modules as registry
from ...core.modules import MANAGE
from ...utils import today

# Numéros de téléphone de la plage réservée à la fiction (04 65 71 xx xx)
# (entreprise, statut visé, origine, contact, email, téléphone, ville, notes)
LEADS = [
    ("Brasserie des Canuts", "new", "website", "Mathieu Perrin", "mathieu@brasserie-des-canuts.example",
     "04 65 71 52 30", "Lyon", "Demande reçue par le formulaire du site : étiquettes pour une gamme de bières artisanales."),
    ("Librairie Passages", "qualified", "referral", "Élise Fontaine", "elise@librairie-passages.example",
     "04 65 71 63 18", "Lyon", "Recommandée par Atelier Nova. Veut renouveler son identité visuelle pour ses vingt ans."),
    ("Cave Saint-Jean", "contacted", "event", "Paul Mercier", "paul@cave-saint-jean.example", "04 65 71 74 41", "Lyon",
     "Rencontré au salon des vins de Lyon : coffrets cadeaux et étiquettes pour les fêtes."),
    ("Studio Kinema", "lost", "cold", "Sarah Lambert", "sarah@studio-kinema.example", "", "Villeurbanne",
     "Pas de projet d'impression cette année ; à recontacter l'an prochain."),
    ("Pixel & Co Studio", "converted", "social", "Inès Robert", "ines@pixelandco.example", "", "Bordeaux",
     "Devenu client : voir la fiche Pixel & Co dans les Ventes."),
]
CONVERTED_TO = {"Pixel & Co Studio": "Pixel & Co"}  # client existant des Ventes, sans en créer un nouveau

# (intitulé, client des Ventes ou prospect, étape visée, montant HT, clôture prévue dans … jours, notes)
OPPORTUNITIES = [
    ("Signalétique du showroom", ("client", "Atelier Nova"), "negotiation", 3200, 12,
     "Totem d'accueil, vitrophanie et plaques de bureau."),
    ("Rapport annuel {year}", ("client", "Kairos Conseil"), "proposal", 4800, 25,
     "Mise en page de 48 pages, infographies et impression de 300 exemplaires."),
    ("Identité visuelle", ("lead", "Librairie Passages"), "qualification", 2400, 40,
     "Logo, charte graphique et papeterie pour les vingt ans de la librairie."),
    ("Étiquettes de bières", ("lead", "Brasserie des Canuts"), "prospecting", 1800, 60,
     "Quatre étiquettes et un pack de six à décliner."),
    ("Catalogue printemps", ("client", "Maison Verde"), "won", 2600, -5,
     "Catalogue de 24 pages pour la collection de printemps."),
]

# (type, objet, échéance dans … jours, faite, opportunité (son prospect et son client sont repris), notes)
ACTIVITIES = [
    ("call", "Appeler Mathieu Perrin pour le brief des étiquettes", 1, False, "Étiquettes de bières", ""),
    ("meeting", "Rendez-vous au showroom d'Atelier Nova", 0, False, "Signalétique du showroom",
     "Valider les maquettes du totem et de la vitrophanie."),
    ("email", "Relancer Kairos Conseil sur la proposition du rapport annuel", -3, False, "Rapport annuel {year}", ""),
    ("task", "Envoyer nos références de papeterie à la Librairie Passages", -6, True, "Identité visuelle",
     "Trois kits de papeterie réalisés pour des commerces lyonnais."),
]


def _day(offset: int) -> str:
    return (today() + timedelta(days=offset)).isoformat()


def seed_demo() -> None:
    leads, opportunities, activities = (entities.get(f"crm.{name}") for name in ("leads", "opportunities", "activities"))
    clients = {}
    if registry.is_enabled("sales"):
        clients = {r["name"]: r["id"] for r in db.fetch_all("SELECT id, name FROM clients")}
    year = today().year

    lead_ids = {}
    for company, status, source, contact, email, phone, city, notes in LEADS:
        lead = entities.save_row(leads, {"company": company, "source": source, "contact_name": contact, "email": email,
                                         "phone": phone, "city": city, "notes": notes}, MANAGE)
        lead_ids[company] = lead
        if status in ("contacted", "qualified"):
            entities.run_action(leads, lead, "contacted", {}, {}, MANAGE)
        if status == "qualified":
            entities.run_action(leads, lead, "qualify", {}, {}, MANAGE)
        if status == "lost":
            entities.run_action(leads, lead, "lost", {}, {}, MANAGE)
        if status == "converted" and clients.get(CONVERTED_TO[company]):
            db.execute("UPDATE crm_leads SET status = 'converted', client_id = ?, updated_at = ? WHERE id = ?",
                       (clients[CONVERTED_TO[company]], db.now_iso(), lead))

    opportunity_ids = {}
    for title, (kind, name), stage, amount, close_in, notes in OPPORTUNITIES:
        title = title.format(year=year)
        link = {"client_id": clients.get(name)} if kind == "client" else {"lead_id": lead_ids.get(name)}
        if not any(link.values()):  # client absent (Ventes désactivées) : l'opportunité n'aurait ni client ni prospect
            continue
        opportunity = entities.save_row(opportunities, {
            "title": title, **link, "amount": amount, "stage": stage if stage != "won" else "negotiation",
            "expected_close": _day(close_in), "notes": notes}, MANAGE)
        opportunity_ids[title] = opportunity
        if stage == "won":
            entities.run_action(opportunities, opportunity, "won", {}, {}, MANAGE)

    for kind, subject, due_in, done, opportunity, notes in ACTIVITIES:
        activity = entities.save_row(activities, {
            "kind": kind, "subject": subject, "due_date": _day(due_in), "notes": notes,
            "opportunity_id": opportunity_ids.get(opportunity.format(year=year)),
        }, MANAGE)
        if done:  # faite le jour de son échéance
            entities.run_action(activities, activity, "done", {}, {}, MANAGE)
            db.execute("UPDATE crm_activities SET done_on = ? WHERE id = ?", (_day(due_in), activity))
