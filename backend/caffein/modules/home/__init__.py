# SPDX-License-Identifier: AGPL-3.0-or-later
"""Accueil : tableau de bord (chiffres clés de chaque module, échéances, activité, actualités) et « Mes vues »."""

from __future__ import annotations

from ... import services
from ...core.modules import Kpi, Module, Page
from . import routes


def _time_saved() -> dict:
    return {"value": services.time_saved_minutes()}


MODULE = Module(
    key="home", slug="accueil", label=("Accueil", "Home"),
    description=("Tableau de bord : chiffres clés de chaque module, échéances, activité et « Mes vues ».",
                 "Dashboard: key figures from every module, deadlines, activity and “My views”."),
    icon="House", order=0, core=True,
    pages=[
        Page("tableau-de-bord", ("Tableau de bord", "Dashboard"), component="home.dashboard", path="/",
             icon="LayoutDashboard"),
        Page("vues", ("Mes vues", "My views"), component="home.views", icon="Sparkles"),
    ],
    router=routes.router,
    jobs=("onboarding_emails", "newsletter_notifications"),
    kpis=[
        Kpi("time_saved", ("Temps gagné", "Time saved"), _time_saved, unit="minutes",
            foot=("grâce aux automatisations", "thanks to automations"), icon="Clock3",
            path="/parametres/automatisations"),
    ],
)
