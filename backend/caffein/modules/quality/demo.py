# SPDX-License-Identifier: AGPL-3.0-or-later
"""Données de démonstration de la Qualité : trois non-conformités du Studio Durand (un défaut fournisseur avec ses
actions en cours, une réclamation client clôturée, un défaut interne tout juste déclaré).

L'article, le fournisseur, le client et les responsables sont repris des autres modules s'ils sont actifs et que la
fiche existe ; rien n'y est créé."""

from __future__ import annotations

from datetime import timedelta

from ... import db
from ...core import entities
from ...core import modules as registry
from ...core.modules import MANAGE
from ...utils import today

BOX = "Boîte cadeau kraft 22×16 cm"
CARDS = "Jeu de cartes de visite (100 ex.)"


def _day(offset: int) -> str:
    return (today() + timedelta(days=offset)).isoformat()


def _ids(module: str, sql: str) -> dict[str, int]:
    """{nom: id} des fiches d'un autre module, seulement s'il est actif."""
    if not registry.is_enabled(module):
        return {}
    return {r["name"]: r["id"] for r in db.fetch_all(sql)}


def seed_demo() -> None:
    nonconformities = entities.get("quality.nonconformities")
    articles = _ids("technical", "SELECT id, name FROM technical_articles")
    suppliers = _ids("purchases", "SELECT id, name FROM purchases_suppliers")
    clients = _ids("sales", "SELECT id, name FROM clients")
    employees = _ids("hr", "SELECT id, full_name AS name FROM hr_employees")
    lea, hugo = employees.get("Léa Bernard"), employees.get("Hugo Martin")

    def save(data: dict) -> int:
        return entities.save_row(nonconformities, data, MANAGE)

    def act(row_id: int, action: str, payload: dict | None = None) -> None:
        entities.run_action(nonconformities, row_id, action, payload or {}, {}, MANAGE)

    # Défaut fournisseur : actions en cours (l'une faite, l'autre à venir)
    crushed = save({
        "title": "Boîtes kraft écrasées à la livraison", "detected_on": _day(-9), "origin": "supplier", "severity": "major",
        "article_id": articles.get(BOX), "supplier_id": suppliers.get("Emballages du Rhône"), "quantity_affected": 12,
        "cost": 16.20,
        "description": "12 boîtes sur 100 arrivées les coins enfoncés : inutilisables pour les kits de papeterie.",
        "root_cause": "Cartons de transport trop grands et calage insuffisant : les boîtes ont bougé pendant le "
                      "transport.",
        "actions": [
            {"kind": "corrective", "description": "Retour au fournisseur et avoir", "owner_id": lea, "due_date": _day(-4),
             "done": True, "done_on": _day(-5)},
            {"kind": "preventive", "description": "Contrôle à réception des emballages", "owner_id": hugo,
             "due_date": _day(7)},
        ],
    })
    act(crushed, "analyse")
    act(crushed, "plan")

    # Réclamation client : traitée et clôturée il y a 20 jours
    tint = save({
        "title": "Erreur de teinte sur des cartes de visite", "detected_on": _day(-31), "origin": "customer",
        "severity": "minor", "article_id": articles.get(CARDS), "client_id": clients.get("Atelier Nova"),
        "quantity_affected": 1, "cost": 45,
        "description": "Le bleu des cartes livrées est plus soutenu que sur le bon à tirer validé par le client.",
        "root_cause": "Profil colorimétrique de l'imprimante pas mis à jour après le changement de papier.",
        "actions": [
            {"kind": "corrective", "description": "Réimpression des cartes à nos frais", "owner_id": hugo,
             "due_date": _day(-27), "done": True, "done_on": _day(-28)},
            {"kind": "preventive", "description": "Étalonnage de l'imprimante à chaque changement de papier",
             "owner_id": hugo, "due_date": _day(-21), "done": True, "done_on": _day(-22)},
        ],
    })
    act(tint, "analyse")
    act(tint, "plan")
    act(tint, "close", {"date": _day(-20)})

    # Défaut interne critique, déclaré hier : à analyser
    save({
        "title": "Coupe décalée au massicot", "detected_on": _day(-1), "origin": "internal", "severity": "critical",
        "article_id": articles.get(CARDS), "quantity_affected": 3,
        "description": "Trois lots de cartes de visite coupés à 2 mm des repères : coupe à reprendre avant livraison.",
    })
