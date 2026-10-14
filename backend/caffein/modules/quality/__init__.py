# SPDX-License-Identifier: AGPL-3.0-or-later
"""Qualité : Non-conformités, actions correctives et préventives. (module en construction : pas encore de page)."""

from __future__ import annotations

from ...core.modules import Module

MODULE = Module(
    key="quality", slug="qualite", label=('Qualité', 'Quality'),
    description=('Non-conformités, actions correctives et préventives.', 'Non-conformities, corrective and preventive actions.'),
    icon="BadgeCheck", order=80,
)
