# SPDX-License-Identifier: AGPL-3.0-or-later
"""Données de démonstration : l'atelier du studio fabrique ses kits de papeterie et ses jeux de cartes de visite.

Un ordre terminé (le stock a reçu les kits et fourni les composants), un ordre lancé dans les temps, un ordre lancé
en retard et un brouillon, sur les articles, nomenclatures et gammes de démonstration des Données techniques."""

from __future__ import annotations

from datetime import timedelta

from ... import db
from ...core import entities
from ...core import modules as registry
from ...core.modules import MANAGE
from ...utils import today
from ..technical import services as technical

KIT, CARDS = "Kit papeterie de marque", "Jeu de cartes de visite (100 ex.)"

# (article, quantité, début prévu, fin prévue (jours par rapport à aujourd'hui), statut visé, notes)
ORDERS = [
    (KIT, 4, -3, 0, "done", "Trois kits pour la commande d'Atelier Nova, un pour la vitrine du studio."),
    (KIT, 5, 0, 4, "released", "Réassort du stock de kits."),
    (CARDS, 20, -6, -2, "released", "Cartes de visite pour les prochains kits."),
    (CARDS, 10, 3, 6, "draft", "Réassort des cartes de visite, à lancer après les kits."),
]


def _day(offset: int) -> str:
    return (today() + timedelta(days=offset)).isoformat()


def seed_demo() -> None:
    if not registry.is_enabled("technical"):
        return
    orders = entities.get("production.orders")
    articles = {r["name"]: r["id"] for r in db.fetch_all("SELECT id, name FROM technical_articles WHERE name IN (?, ?)",
                                                         (KIT, CARDS))}
    for name, quantity, start, end, status, notes in ORDERS:
        article = articles.get(name)
        if article is None:
            continue
        order_id = entities.save_row(orders, {"article_id": article, "quantity": quantity, "planned_start": _day(start),
                                              "planned_end": _day(end), "notes": notes}, MANAGE)
        if status == "draft" or not technical.active_bom(article):  # sans nomenclature, l'ordre reste en brouillon
            continue
        entities.run_action(orders, order_id, "release", {}, {}, MANAGE)
        if status == "done":  # la Logistique, active en démonstration, reçoit les kits et fournit les composants
            entities.run_action(orders, order_id, "complete", {}, {}, MANAGE)
