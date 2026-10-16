# SPDX-License-Identifier: AGPL-3.0-or-later
"""Erreurs métier communes, traduites en réponses HTTP par l'API (404, 409, 403)."""


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class Forbidden(Exception):
    pass
