# SPDX-License-Identifier: AGPL-3.0-or-later
"""Événements entre modules.

Un module ne connaît pas les autres : il annonce ce qui se passe (« sales.order_delivered », « purchases.received »),
et les modules actifs qui s'y sont abonnés (`Module.events`) réagissent. Exemple : la Logistique sort du stock
les articles d'une commande client livrée. Si la Logistique est désactivée, la livraison se fait simplement
sans mouvement de stock : rien ne casse.
"""

from __future__ import annotations

import logging
from typing import Any

from . import modules as registry

log = logging.getLogger("caffein.events")


def emit(event: str, payload: dict[str, Any]) -> list[str]:
    """Prévient les modules actifs abonnés à `event`, dans l'ordre des dépendances, et renvoie leurs messages.
    Une erreur d'un abonné (ValueError, Conflict…) remonte à l'appelant, qui n'enregistre alors pas son changement."""
    messages = []
    for module in registry.dependency_order():
        handler = module.events.get(event)
        if handler is None or not registry.is_enabled(module.key):
            continue
        result = handler(payload)
        if isinstance(result, str) and result:
            messages.append(result)
    return messages


def subscribers(event: str) -> list[str]:
    """Modules actifs abonnés à un événement (diagnostic, tests)."""
    return [m.key for m in registry.dependency_order() if event in m.events and registry.is_enabled(m.key)]
