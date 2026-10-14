# SPDX-License-Identifier: AGPL-3.0-or-later
"""CRM : Prospects, opportunités et actions commerciales. (module en construction : pas encore de page)."""

from __future__ import annotations

from ...core.modules import Module

MODULE = Module(
    key="crm", slug="crm", label=('CRM', 'CRM'),
    description=('Prospects, opportunités et actions commerciales.', 'Leads, opportunities and sales activities.'),
    icon="Handshake", order=45,
)
