# SPDX-License-Identifier: AGPL-3.0-or-later
"""CRM : prospects, opportunités (montants pondérés, devis en un clic) et actions commerciales.

Module entièrement déclaratif : les écrans génériques l'affichent. Le client et le devis viennent des Ventes, utilisées
seulement si elles sont actives (le CRM n'en dépend pas)."""

from __future__ import annotations

from ... import db
from ...core.modules import Kpi, Module, Page, Shortcut
from ...utils import today
from .demo import seed_demo
from .entities import ENTITIES, MIGRATIONS, OPEN_STAGES, open_pipeline


def _open_opportunities() -> dict:
    """Opportunités ni gagnées ni perdues."""
    n = db.fetch_one(f"SELECT COUNT(*) AS n FROM crm_opportunities WHERE stage IN ({', '.join('?' for _ in OPEN_STAGES)})",
                     OPEN_STAGES)["n"]
    return {"value": n, "count": n}


def _activities_due() -> dict:
    """Actions commerciales pas encore faites dont l'échéance est aujourd'hui ou passée."""
    n = db.fetch_one("SELECT COUNT(*) AS n FROM crm_activities WHERE done = 0 AND due_date IS NOT NULL AND due_date <= ?",
                     (today().isoformat(),))["n"]
    return {"value": n, "count": n}


MODULE = Module(
    key="crm", slug="crm", label=("CRM", "CRM"),
    description=("Prospects, opportunités (montants pondérés, devis en un clic) et actions commerciales.",
                 "Leads, opportunities (weighted amounts, one-click quotes) and sales activities."),
    icon="Handshake", order=45,
    migrations=MIGRATIONS, entities=ENTITIES,
    pages=[
        Page("opportunites", ("Opportunités", "Opportunities"), entity="crm.opportunities", icon="Target"),
        Page("prospects", ("Prospects", "Leads"), entity="crm.leads", icon="Contact"),
        Page("actions", ("Actions commerciales", "Sales activities"), entity="crm.activities", icon="ListTodo"),
    ],
    # Libellés complets (l'objet est nommé) : « Mes vues » reconnaît un chiffre clé quand la demande cite son libellé
    kpis=[
        Kpi("pipeline", ("Pipeline commercial pondéré", "Weighted sales pipeline"), open_pipeline, unit="money",
            icon="TrendingUp", foot=("{n} opportunité(s) en cours, HT", "{n} open opportunity(ies), excl. VAT"),
            path="/crm/opportunites"),
        Kpi("open_opportunities", ("Opportunités en cours", "Open opportunities"), _open_opportunities, icon="Target",
            foot=("de la découverte à la négociation", "from prospecting to negotiation"),
            path="/crm/opportunites?view=board"),  # vue en colonnes : une par étape
        Kpi("activities_due", ("Actions commerciales à traiter", "Sales activities due"), _activities_due,
            icon="CalendarClock", foot=("échéance aujourd'hui ou dépassée", "due today or overdue"),
            path="/crm/actions?f_done=0", alert=lambda d: (d.get("value") or 0) > 0),
    ],
    shortcuts=[Shortcut("new_opportunity", ("Nouvelle opportunité", "New opportunity"), "/crm/opportunites?new=1",
                        icon="Target")],
    seed_demo=seed_demo,
    reset_tables=("crm_activities", "crm_opportunities", "crm_leads"),
)
