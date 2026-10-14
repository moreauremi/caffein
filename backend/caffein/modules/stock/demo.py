# SPDX-License-Identifier: AGPL-3.0-or-later
"""Données de démonstration : un entrepôt, une réserve à l'atelier et l'inventaire de départ."""

from __future__ import annotations

from datetime import timedelta

from ... import db
from ...core import entities
from ...core.modules import MANAGE
from ...utils import today
from . import services

# (désignation de l'article, quantité inventoriée) — boîtes et papier de soie sous leur stock minimum
INVENTORY = [
    ("Papier couché 350 g, feuille SRA3", 1200), ("Enveloppe kraft C5", 650), ("Boîte cadeau kraft 22×16 cm", 32),
    ("Papier de soie (feuille)", 150), ("Jeu de cartes de visite (100 ex.)", 14), ("Kit papeterie de marque", 6),
    ("Kakémono 85×200 cm", 3), ("Flyers A5, lot de 500", 4),
]


def seed_demo() -> None:
    warehouses = entities.get("stock.warehouses")
    # L'entrepôt par défaut existe peut-être déjà (livraisons de démonstration des Ventes) : on le complète
    main = services.default_warehouse_id()
    entities.save_row(warehouses, {"address": "18 rue des Lilas, 69003 Lyon"}, MANAGE, main)
    entities.save_row(warehouses, {"name": "Réserve de l'atelier", "address": "Atelier, rez-de-chaussée"}, MANAGE)
    ids = {r["name"]: r["id"] for r in db.fetch_all("SELECT id, name FROM technical_articles")}
    lines = [{"article_id": ids[name], "quantity": qty} for name, qty in INVENTORY if name in ids]
    day = (today() - timedelta(days=45)).isoformat()
    services.post("adjustment", lines, sign=1, reference="Inventaire initial", date=day, source="demo:inventory",
                  warehouse_id=main)
