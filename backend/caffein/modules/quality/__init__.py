# SPDX-License-Identifier: AGPL-3.0-or-later
"""Qualité : non-conformités (réclamations clients, défauts fournisseurs ou internes, audits), actions correctives et
préventives, plan d'actions et coût de la non-qualité.

Module entièrement déclaratif : les écrans génériques l'affichent. L'article, le fournisseur, le client et le
responsable d'une action sont des références facultatives vers les Données techniques, les Achats, les Ventes et les
RH : la Qualité ne dépend d'aucun module."""

from __future__ import annotations

from ... import db
from ...core.modules import Kpi, Module, Page, Shortcut
from ...utils import cents, today
from .demo import seed_demo
from .entities import ENTITIES, MIGRATIONS


def _open_nonconformities() -> dict:
    """Non-conformités pas encore clôturées, et combien d'entre elles sont critiques."""
    row = db.fetch_one("SELECT COUNT(*) AS n, COALESCE(SUM(severity = 'critical'), 0) AS critical "
                       "FROM quality_nonconformities WHERE status != 'closed'")
    return {"value": row["n"], "count": row["critical"]}


def _overdue_actions() -> dict:
    """Actions correctives ou préventives pas encore faites dont l'échéance est passée (règle du plan d'actions)."""
    n = db.fetch_one("SELECT COUNT(*) AS n FROM quality_actions WHERE done = 0 AND due_date IS NOT NULL AND due_date < ?",
                     (today().isoformat(),))["n"]
    return {"value": n, "count": n}


def _cost_year() -> dict:
    """Coût de la non-qualité des non-conformités détectées cette année, et leur nombre."""
    start = today().replace(month=1, day=1).isoformat()
    end = today().replace(month=12, day=31).isoformat()
    row = db.fetch_one("SELECT COUNT(*) AS n, COALESCE(SUM(cost), 0) AS total FROM quality_nonconformities "
                       "WHERE detected_on >= ? AND detected_on <= ?", (start, end))
    return {"value": cents(row["total"] or 0), "count": row["n"]}


MODULE = Module(
    key="quality", slug="qualite", label=("Qualité", "Quality"),
    description=("Non-conformités, actions correctives et préventives, plan d'actions et coût de la non-qualité.",
                 "Non-conformities, corrective and preventive actions, action plan and cost of poor quality."),
    icon="BadgeCheck", order=80,
    migrations=MIGRATIONS, entities=ENTITIES,
    pages=[
        Page("non-conformites", ("Non-conformités", "Non-conformities"), entity="quality.nonconformities",
             icon="FileWarning"),
        Page("plan-actions", ("Plan d'actions", "Action plan"), entity="quality.action_plan", icon="ListChecks"),
    ],
    # Libellés complets (l'objet est nommé) : « Mes vues » reconnaît un chiffre clé quand la demande cite son libellé
    kpis=[
        Kpi("open_nonconformities", ("Non-conformités ouvertes", "Open non-conformities"), _open_nonconformities,
            icon="FileWarning", foot=("dont {n} critique(s)", "including {n} critical"),
            path="/qualite/non-conformites?view=board", alert=lambda d: (d.get("count") or 0) > 0),
        Kpi("overdue_actions", ("Actions qualité en retard", "Overdue quality actions"), _overdue_actions,
            icon="CalendarClock", foot=("échéance dépassée", "past their due date"),
            path="/qualite/plan-actions?f_done=0&sort=due_date", alert=lambda d: (d.get("value") or 0) > 0),
        Kpi("cost_year", ("Coût de la non-qualité de l'année", "Cost of poor quality this year"), _cost_year,
            unit="money", icon="Coins", foot=("{n} non-conformité(s) détectée(s)", "{n} non-conformity(ies) detected"),
            path="/qualite/non-conformites"),
    ],
    shortcuts=[Shortcut("new_nonconformity", ("Déclarer une non-conformité", "Report a non-conformity"),
                        "/qualite/non-conformites?new=1", icon="FileWarning")],
    seed_demo=seed_demo,
    reset_tables=("quality_actions", "quality_nonconformities"),
)
