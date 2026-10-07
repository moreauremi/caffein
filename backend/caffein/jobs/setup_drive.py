# SPDX-License-Identifier: AGPL-3.0-or-later
"""Mise en place de l'arborescence de classement.

Remplace le workflow n8n « Caffein - First Connection v2 » (création des dossiers
Google Drive « Factures à traiter », « Factures », « Ne pas trier », puis
déplacement des fichiers sélectionnés). Ici le « Drive » est un dossier local :
data/drive/Caffein/. Les fichiers déposés à sa racine sont rangés dans
« Factures à traiter » (sélectionnés) ou « Ne pas trier » (les autres).

    python -m caffein run setup_drive
"""

from __future__ import annotations

import shutil

from .. import config
from ..utils import unique_path
from . import job, on_event


def tree() -> list[dict]:
    out = []
    for key, path in config.FOLDERS.items():
        files = [p for p in path.rglob("*") if p.is_file() and not p.name.startswith(".")] if path.exists() else []
        out.append({"key": key, "path": str(path.relative_to(config.DRIVE_DIR.parent)), "files": len(files)})
    return out


def root_files() -> list[str]:
    if not config.DRIVE_DIR.exists():
        return []
    return sorted(p.name for p in config.DRIVE_DIR.iterdir() if p.is_file() and not p.name.startswith("."))


@job(
    "setup_drive",
    title="Configuration du classement",
    description="Crée l'arborescence Caffein (Factures à traiter, Factures envoyées/reçues, Contrats, Reçus, Ne pas trier) "
                "et range les fichiers déposés à la racine.",
    replaces="Caffein - First Connection v2",
    schedule=on_event("À la première connexion, ou à la demande"),
)
def run(selected: list[str] | None = None) -> dict:
    config.ensure_dirs()
    moved = {"a_traiter": [], "ne_pas_trier": []}
    files = root_files()
    keep = set(files if selected is None else selected)
    for name in files:
        target = "a_traiter" if name in keep else "ne_pas_trier"
        shutil.move(str(config.DRIVE_DIR / name), unique_path(config.FOLDERS[target] / name))
        moved[target].append(name)
    summary = "Arborescence vérifiée"
    if files:
        summary += f" · {len(moved['a_traiter'])} fichier(s) à traiter, {len(moved['ne_pas_trier'])} exclu(s)"
    return {"summary": summary, "notable": bool(files), "moved": moved, "folders": tree()}
