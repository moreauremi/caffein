# SPDX-License-Identifier: AGPL-3.0-or-later
"""Paramètres : compte, entreprise, utilisateurs, rôles et droits, modules, automatisations."""

from __future__ import annotations

from ...core.modules import Module, Page
from . import routes

MODULE = Module(
    key="settings", slug="parametres", label=("Paramètres", "Settings"),
    description=("Votre compte, l'entreprise, les utilisateurs et leurs droits, les modules actifs, les automatisations.",
                 "Your account, the company, users and their permissions, active modules, automations."),
    icon="Settings", order=1000, core=True,
    pages=[
        Page("compte", ("Mon compte", "My account"), component="settings.account", icon="UserRound"),
        Page("apparence", ("Apparence", "Appearance"), component="settings.appearance", icon="Palette"),
        Page("entreprise", ("Entreprise", "Company"), component="settings.company", admin_only=True, icon="Building2"),
        Page("fiscalite", ("Fiscalité", "Tax"), component="settings.fiscal", admin_only=True, icon="Landmark"),
        Page("notifications", ("Notifications", "Notifications"), component="settings.notifications", admin_only=True,
             icon="Bell"),
        Page("utilisateurs", ("Utilisateurs", "Users"), component="settings.users", admin_only=True, icon="UsersRound"),
        Page("roles", ("Rôles et droits", "Roles"), component="settings.roles", admin_only=True, icon="ShieldCheck"),
        Page("modules", ("Modules", "Modules"), component="settings.modules", admin_only=True, icon="Blocks"),
        Page("automatisations", ("Automatisations", "Automations"), component="settings.automations", icon="Bot"),
        Page("a-propos", ("À propos", "About"), component="settings.about", icon="Info"),
    ],
    router=routes.router,
)
