# SPDX-License-Identifier: AGPL-3.0-or-later
"""Achats : Fournisseurs, commandes fournisseurs et réceptions. (module en construction : pas encore de page)."""

from __future__ import annotations

from ...core.modules import Module

MODULE = Module(
    key="purchases", slug="achats", label=('Achats', 'Purchasing'),
    description=('Fournisseurs, commandes fournisseurs et réceptions.', 'Suppliers, purchase orders and receipts.'),
    icon="ShoppingCart", order=30,
)
