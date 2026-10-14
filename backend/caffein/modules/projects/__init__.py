# SPDX-License-Identifier: AGPL-3.0-or-later
"""Projets : Projets, tâches, temps passés et facturation des temps. (module en construction : pas encore de page)."""

from __future__ import annotations

from ...core.modules import Module

MODULE = Module(
    key="projects", slug="projets", label=('Projets', 'Projects'),
    description=('Projets, tâches, temps passés et facturation des temps.', 'Projects, tasks, timesheets and time billing.'),
    icon="FolderKanban", order=70,
)
