# SPDX-License-Identifier: AGPL-3.0-or-later
"""Production : Ordres de fabrication, besoins en composants, charge des postes. (module en construction : pas encore de page)."""

from __future__ import annotations

from ...core.modules import Module

MODULE = Module(
    key="production", slug="production", label=('Production', 'Production'),
    description=('Ordres de fabrication, besoins en composants, charge des postes.', 'Manufacturing orders, component needs, work centre load.'),
    icon="Factory", order=50, depends=('technical', 'stock'),
)
