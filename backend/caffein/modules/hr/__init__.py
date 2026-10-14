# SPDX-License-Identifier: AGPL-3.0-or-later
"""RH : Services, salariés, absences et congés. (module en construction : pas encore de page)."""

from __future__ import annotations

from ...core.modules import Module

MODULE = Module(
    key="hr", slug="rh", label=('RH', 'HR'),
    description=('Services, salariés, absences et congés.', 'Departments, employees, absences and leave.'),
    icon="Users", order=20,
)
