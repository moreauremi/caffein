# SPDX-License-Identifier: AGPL-3.0-or-later
"""Modules de Caffein (voir docs/modules.md).

Ajouter un module : créer son paquet `caffein/modules/<clé>/` qui expose `MODULE`, puis l'ajouter à `MODULES`.
L'ordre de la liste n'a pas d'importance : la navigation suit `Module.order`, les migrations suivent les dépendances.
"""

from . import accounting, crm, home, hr, maintenance, production, projects, purchases, quality, sales, settings, stock, technical

MODULES = [
    home.MODULE,
    technical.MODULE,
    hr.MODULE,
    purchases.MODULE,
    sales.MODULE,
    crm.MODULE,
    production.MODULE,
    stock.MODULE,
    projects.MODULE,
    quality.MODULE,
    maintenance.MODULE,
    accounting.MODULE,
    settings.MODULE,
]
