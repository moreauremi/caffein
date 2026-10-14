# SPDX-License-Identifier: AGPL-3.0-or-later
"""Données de démonstration : un studio qui conçoit et fabrique des kits de papeterie pour ses clients."""

from __future__ import annotations

from ...core import entities
from ...core.modules import MANAGE

FAMILIES = ["Papiers et supports", "Fournitures d'emballage", "Produits finis", "Impression sous-traitée", "Prestations"]

# (désignation, type, famille, unité, prix de vente, coût d'achat, stock mini, qté à commander, délai)
ARTICLES = [
    ("Papier couché 350 g, feuille SRA3", "raw", 0, "feuille", None, 0.42, 500, 2000, 5),
    ("Enveloppe kraft C5", "raw", 1, "u", None, 0.18, 300, 1000, 7),
    ("Boîte cadeau kraft 22×16 cm", "raw", 1, "u", None, 1.35, 40, 100, 10),
    ("Papier de soie (feuille)", "raw", 1, "feuille", None, 0.09, 200, 500, 7),
    ("Jeu de cartes de visite (100 ex.)", "semi", 2, "lot", 45, None, 10, 20, None),
    ("Kit papeterie de marque", "finished", 2, "u", 290, None, 5, 10, None),
    ("Kakémono 85×200 cm", "goods", 3, "u", 129, 62, 2, 5, 12),
    ("Flyers A5, lot de 500", "goods", 3, "lot", 95, 38, None, None, 6),
    ("Heure de conception graphique", "service", 4, "h", 65, None, None, None, None),
]


def seed_demo() -> None:
    def save(entity: str, data: dict) -> int:
        return entities.save_row(entities.get(f"technical.{entity}"), data, MANAGE)

    families = [save("families", {"name": name}) for name in FAMILIES]
    ids = []
    for name, kind, family, unit, sale, cost, min_stock, reorder, lead in ARTICLES:
        ids.append(save("articles", {"name": name, "kind": kind, "family_id": families[family], "unit": unit,
                                     "sale_price": sale, "purchase_price": cost, "min_stock": min_stock,
                                     "reorder_qty": reorder, "lead_time_days": lead}))
    paper, envelope, box, tissue, cards, kit = ids[:6]
    save("boms", {"article_id": cards, "name": "Cartes de visite recto-verso", "quantity": 1,
                  "lines": [{"article_id": paper, "quantity": 5, "scrap_rate": 4}]})
    save("boms", {"article_id": kit, "name": "Kit standard", "quantity": 1, "lines": [
        {"article_id": cards, "quantity": 1}, {"article_id": envelope, "quantity": 25, "scrap_rate": 2},
        {"article_id": paper, "quantity": 10, "scrap_rate": 3}, {"article_id": box, "quantity": 1},
        {"article_id": tissue, "quantity": 4}]})
    printer = save("workcenters", {"name": "Imprimante numérique", "kind": "machine", "hourly_cost": 45, "capacity_hours": 7})
    cutter = save("workcenters", {"name": "Massicot", "kind": "machine", "hourly_cost": 30, "capacity_hours": 7})
    bench = save("workcenters", {"name": "Atelier de façonnage", "kind": "manual", "hourly_cost": 32, "capacity_hours": 7})
    save("routings", {"article_id": cards, "name": "Impression et découpe", "steps": [
        {"workcenter_id": printer, "description": "Impression recto-verso", "setup_minutes": 10, "run_minutes": 4},
        {"workcenter_id": cutter, "description": "Découpe au format", "setup_minutes": 5, "run_minutes": 3}]})
    save("routings", {"article_id": kit, "name": "Fabrication du kit", "steps": [
        {"workcenter_id": printer, "description": "Impression des en-têtes", "setup_minutes": 15, "run_minutes": 8},
        {"workcenter_id": cutter, "description": "Découpe", "setup_minutes": 5, "run_minutes": 4},
        {"workcenter_id": bench, "description": "Assemblage et emballage", "run_minutes": 20}]})
