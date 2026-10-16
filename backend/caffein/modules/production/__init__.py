# SPDX-License-Identifier: AGPL-3.0-or-later
"""Production : ordres de fabrication (besoins en composants, manques, temps et coûts calculés), charge des postes.

Terminer un ordre annonce `production.order_completed` : la Logistique fait entrer le produit en stock et en sort
les composants consommés."""

from __future__ import annotations

from ... import db
from ...core.modules import Kpi, Module, Page, Shortcut
from ...utils import add_months, today
from .demo import seed_demo
from .entities import ENTITIES, MIGRATIONS, REFERENCES


def _count(where: str, params: tuple = ()) -> dict:
    n = db.fetch_one(f"SELECT COUNT(*) AS n FROM production_orders WHERE {where}", params)["n"]
    return {"value": n, "count": n}


def _in_progress() -> dict:
    """Ordres lancés, pas encore terminés."""
    return _count("status = 'released'")


def _late() -> dict:
    """Ordres lancés dont la fin prévue est passée (même règle que la colonne « En retard »)."""
    return _count("status = 'released' AND planned_end IS NOT NULL AND planned_end < ?", (today().isoformat(),))


def _completed_month() -> dict:
    """Ordres terminés ce mois-ci."""
    start = today().replace(day=1)
    return _count("status = 'done' AND completed_on >= ? AND completed_on < ?",
                  (start.isoformat(), add_months(start, 1).isoformat()))


MODULE = Module(
    key="production", slug="production", label=("Production", "Production"),
    description=("Ordres de fabrication (besoins en composants, manques, temps et coûts calculés), charge des postes. "
                 "Terminer un ordre met le stock à jour.",
                 "Manufacturing orders (component needs, shortages, times and costs calculated), work centre load. "
                 "Completing an order updates the stock."),
    icon="Factory", order=50, depends=("technical", "stock"),
    migrations=MIGRATIONS, entities=ENTITIES,
    pages=[
        Page("ordres", ("Ordres de fabrication", "Manufacturing orders"), entity="production.orders", icon="Factory"),
        Page("charge", ("Charge des postes", "Work centre load"), entity="production.load", icon="Gauge"),
    ],
    # Libellés complets (l'objet est nommé) : « Mes vues » reconnaît un chiffre clé quand la demande cite son libellé
    kpis=[
        Kpi("in_progress", ("Ordres de fabrication en cours", "Manufacturing orders in progress"), _in_progress,
            icon="Hammer", foot=("lancés, pas encore terminés", "released, not yet completed"),
            path="/production/ordres?f_status=released"),
        Kpi("late", ("Ordres de fabrication en retard", "Late manufacturing orders"), _late, icon="CalendarClock",
            foot=("fin prévue dépassée", "planned end date passed"), path="/production/ordres?f_status=released&sort=planned_end",
            alert=lambda d: (d.get("value") or 0) > 0),
        Kpi("completed_month", ("Ordres de fabrication terminés ce mois", "Manufacturing orders completed this month"),
            _completed_month, icon="PackageCheck", foot=("produits entrés en stock", "output added to stock"),
            path="/production/ordres?f_status=done"),
    ],
    shortcuts=[Shortcut("new_order", ("Ordre de fabrication", "Manufacturing order"), "/production/ordres?new=1",
                        icon="Factory")],
    references=REFERENCES,
    seed_demo=seed_demo,
    reset_tables=("production_order_operations", "production_order_components", "production_orders"),
)
