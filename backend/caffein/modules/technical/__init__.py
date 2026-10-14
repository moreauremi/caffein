# SPDX-License-Identifier: AGPL-3.0-or-later
"""Données techniques : le référentiel des articles, nomenclatures, postes de charge et gammes."""

from __future__ import annotations

from ... import db
from ...core.modules import Kpi, Module, Page, Shortcut
from .demo import seed_demo
from .entities import ENTITIES, MIGRATIONS


def _active_articles() -> dict:
    n = db.fetch_one("SELECT COUNT(*) AS n FROM technical_articles WHERE active = 1")["n"]
    return {"value": n, "count": n}


def _without_bom() -> dict:
    """Produits fabriqués (finis, semi-finis) sans nomenclature active : la production ne saurait pas quoi consommer."""
    n = db.fetch_one("""SELECT COUNT(*) AS n FROM technical_articles a
                        WHERE a.active = 1 AND a.kind IN ('finished', 'semi')
                          AND NOT EXISTS (SELECT 1 FROM technical_boms b WHERE b.article_id = a.id AND b.active = 1)""")["n"]
    return {"value": n, "count": n}


MODULE = Module(
    key="technical", slug="donnees-techniques", label=("Données techniques", "Technical data"),
    description=("Articles, familles, nomenclatures, postes de charge et gammes : le référentiel commun aux autres modules.",
                 "Items, families, bills of materials, work centres and routings: the catalogue shared by the other modules."),
    icon="Boxes", order=10,
    migrations=MIGRATIONS, entities=ENTITIES,
    pages=[
        Page("articles", ("Articles", "Items"), entity="technical.articles", icon="Package"),
        Page("familles", ("Familles", "Families"), entity="technical.families", icon="Layers"),
        Page("nomenclatures", ("Nomenclatures", "Bills of materials"), entity="technical.boms", icon="ListTree"),
        Page("postes", ("Postes de charge", "Work centres"), entity="technical.workcenters", icon="Cog"),
        Page("gammes", ("Gammes", "Routings"), entity="technical.routings", icon="Route"),
    ],
    kpis=[
        Kpi("active_articles", ("Articles actifs", "Active items"), _active_articles, icon="Package",
            foot=("dans le référentiel", "in the catalogue"), path="/donnees-techniques/articles?f_active=1"),
        Kpi("without_bom", ("Produits sans nomenclature", "Products without a bill"), _without_bom, icon="ListTree",
            foot=("finis ou semi-finis", "finished or semi-finished"), path="/donnees-techniques/articles?f_kind=finished",
            alert=lambda d: (d.get("value") or 0) > 0),
    ],
    shortcuts=[Shortcut("new_article", ("Nouvel article", "New item"), "/donnees-techniques/articles?new=1", icon="Package")],
    seed_demo=seed_demo,
    reset_tables=("technical_routing_steps", "technical_routings", "technical_bom_lines", "technical_boms",
                  "technical_articles", "technical_workcenters", "technical_families"),
)
