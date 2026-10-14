# SPDX-License-Identifier: AGPL-3.0-or-later
"""Modules de Caffein (voir docs/modules.md).

Ajouter un module : créer son paquet `caffein/modules/<clé>/` qui expose `MODULE`, puis l'ajouter à `MODULES`.
L'ordre de la liste n'a pas d'importance : la navigation suit `Module.order`, les migrations suivent les dépendances.
"""

from . import accounting, home, sales, settings

MODULES = [
    home.MODULE,
    sales.MODULE,
    accounting.MODULE,
    settings.MODULE,
]
