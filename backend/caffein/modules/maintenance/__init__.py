# SPDX-License-Identifier: AGPL-3.0-or-later
"""Maintenance : équipements (périodicité, prochaine maintenance calculée) et interventions préventives ou correctives.

Module entièrement déclaratif : les écrans génériques l'affichent. Le poste de charge, le fournisseur et le technicien
sont des références facultatives vers les Données techniques, les Achats et les RH : la Maintenance ne dépend d'aucun
module."""

from __future__ import annotations

from ... import db
from ...core.modules import Kpi, Module, Page, Shortcut
from ...utils import cents, today
from .demo import seed_demo
from .entities import ENTITIES, MIGRATIONS, due_equipment


def _equipment_down() -> dict:
    n = db.fetch_one("SELECT COUNT(*) AS n FROM maintenance_equipment WHERE status = 'down'")["n"]
    return {"value": n, "count": n}


def _cost_year() -> dict:
    """Coût des interventions terminées cette année, et leur nombre."""
    start = today().replace(month=1, day=1).isoformat()
    end = today().replace(month=12, day=31).isoformat()
    row = db.fetch_one("SELECT COUNT(*) AS n, COALESCE(SUM(cost), 0) AS total FROM maintenance_interventions "
                       "WHERE status = 'done' AND done_on >= ? AND done_on <= ?", (start, end))
    return {"value": cents(row["total"] or 0), "count": row["n"]}


MODULE = Module(
    key="maintenance", slug="maintenance", label=("Maintenance", "Maintenance"),
    description=("Équipements, interventions préventives et correctives : prochaines maintenances calculées, "
                 "équipements en panne suivis.",
                 "Equipment, preventive and corrective maintenance: next maintenance calculated, equipment breakdowns "
                 "tracked."),
    icon="Wrench", order=85,
    migrations=MIGRATIONS, entities=ENTITIES,
    pages=[
        Page("interventions", ("Interventions", "Maintenance jobs"), entity="maintenance.interventions", icon="Wrench"),
        Page("equipements", ("Équipements", "Equipment"), entity="maintenance.equipment", icon="Gauge"),
    ],
    # Libellés complets (l'objet est nommé) : « Mes vues » reconnaît un chiffre clé quand la demande cite son libellé
    kpis=[
        Kpi("maintenance_due", ("Maintenances préventives à prévoir", "Preventive maintenance due"), due_equipment,
            icon="CalendarClock", foot=("équipement(s), dont {n} en retard", "equipment, {n} overdue"),
            path="/maintenance/equipements", alert=lambda d: (d.get("value") or 0) > 0),
        Kpi("equipment_down", ("Équipements en panne", "Equipment down"), _equipment_down, icon="Siren",
            foot=("à remettre en service", "to bring back into service"), path="/maintenance/equipements?f_status=down",
            alert=lambda d: (d.get("value") or 0) > 0),
        Kpi("cost_year", ("Coût de la maintenance de l'année", "Maintenance cost this year"), _cost_year, unit="money",
            icon="Coins", foot=("{n} intervention(s) terminée(s)", "{n} completed job(s)"), path="/maintenance/interventions"),
    ],
    shortcuts=[Shortcut("new_intervention", ("Intervention", "Maintenance job"), "/maintenance/interventions?new=1",
                        icon="Wrench")],
    seed_demo=seed_demo,
    reset_tables=("maintenance_interventions", "maintenance_equipment"),
)
