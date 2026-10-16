# SPDX-License-Identifier: AGPL-3.0-or-later
"""Migrations des modules.

Le socle (db.py) a ses propres migrations, numérotées par `PRAGMA user_version`. Chaque module a les siennes,
numérotées à partir de 1 et suivies dans la table `schema_migrations` : ajouter un module ou une version
ne touche ni au socle ni aux autres modules. Une version publiée ne se modifie jamais.
"""

from __future__ import annotations

import re

from .. import db

_KEY = re.compile(r"^[a-z][a-z_]*$")


def apply_all() -> None:
    """Applique les migrations manquantes de chaque module (dans l'ordre des dépendances), puis
    synchronise la table `modules`. Appelée par db.init_db(), après les migrations du socle."""
    from . import modules as registry

    registry.load()
    fresh = db.fetch_one("SELECT COUNT(*) AS n FROM users")["n"] == 0
    applied = {(r["module"], r["version"]) for r in db.fetch_all("SELECT module, version FROM schema_migrations")}
    for module in registry.dependency_order():
        if not _KEY.match(module.key):
            raise ValueError(f"Clé de module invalide : {module.key!r}")
        versions = [version for version, _ in module.migrations]
        if versions != sorted(set(versions)) or (versions and versions[0] < 1):
            raise ValueError(f"Migrations du module {module.key} : versions croissantes, uniques, à partir de 1.")
        for version, script in module.migrations:
            if (module.key, version) in applied:
                continue
            with db.connect() as conn:
                conn.executescript(
                    f"BEGIN;\n{script}\n"
                    f"INSERT INTO schema_migrations (module, version, applied_at) VALUES ('{module.key}', {int(version)}, "
                    f"'{db.now_iso()}');\nCOMMIT;")
    registry.sync_rows(fresh)


def applied_versions() -> dict[str, int]:
    """Dernière version appliquée de chaque module (page À propos, diagnostic)."""
    rows = db.fetch_all("SELECT module, MAX(version) AS version FROM schema_migrations GROUP BY module")
    return {r["module"]: r["version"] for r in rows}
