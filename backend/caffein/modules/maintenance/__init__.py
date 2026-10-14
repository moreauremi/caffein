# SPDX-License-Identifier: AGPL-3.0-or-later
"""Maintenance : Équipements, interventions préventives et correctives. (module en construction : pas encore de page)."""

from __future__ import annotations

from ...core.modules import Module

MODULE = Module(
    key="maintenance", slug="maintenance", label=('Maintenance', 'Maintenance'),
    description=('Équipements, interventions préventives et correctives.', 'Equipment, preventive and corrective work.'),
    icon="Wrench", order=85,
)
