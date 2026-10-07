# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sauvegarde et restauration d'une instance.

L'archive contient : la base SQLite (copie cohérente via l'API de sauvegarde de
SQLite, utilisable service démarré), les documents classés, la boîte d'envoi et
la clé de chiffrement. Sans la clé, les montants chiffrés sont illisibles : gardez
les sauvegardes en lieu sûr.

    caffein backup                      → <données>/backups/caffein-backup-AAAAMMJJ-HHMMSS.tar.gz
    caffein restore archive.tar.gz --force
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

from . import __version__, config, db

MANIFEST = "caffein-backup.json"
CONTENT_DIRS = ("drive", "outbox")


def backup(output: str | os.PathLike | None = None) -> Path:
    db.init_db()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = Path(output) if output else config.DATA_DIR / "backups" / f"caffein-backup-{stamp}.tar.gz"
    target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "caffein.db"
        src, dst = sqlite3.connect(config.DB_PATH), sqlite3.connect(snapshot)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        manifest = Path(tmp) / MANIFEST
        manifest.write_text(json.dumps({
            "version": __version__, "schema": db.schema_version(), "created_at": datetime.now().isoformat(),
            "key_included": config.KEY_FILE.exists(),
        }, indent=2))

        with tarfile.open(target, "w:gz") as tar:
            tar.add(manifest, arcname=MANIFEST)
            tar.add(snapshot, arcname="caffein.db")
            if config.KEY_FILE.exists():
                tar.add(config.KEY_FILE, arcname=config.KEY_FILE.name)
            for name in CONTENT_DIRS:
                folder = config.DATA_DIR / name
                if folder.exists():
                    tar.add(folder, arcname=name)
    target.chmod(0o600)
    if not config.KEY_FILE.exists():
        print("Attention : la clé de chiffrement vient de CAFFEIN_ENCRYPTION_KEY et n'est pas dans l'archive. "
              "Conservez-la séparément.")
    return target


def _has_data() -> bool:
    if not config.DB_PATH.exists():
        return False
    with sqlite3.connect(config.DB_PATH) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        return "clients" in tables and conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0] > 0


def _checked_members(tar: tarfile.TarFile, root: Path) -> list[tarfile.TarInfo]:
    """Refuse les chemins absolus, « .. », liens et fichiers spéciaux (archives malveillantes)."""
    members = []
    for member in tar.getmembers():
        target = (root / member.name).resolve()
        if member.name.startswith("/") or (target != root and root not in target.parents):
            raise SystemExit(f"Chemin refusé dans l'archive : {member.name}")
        if not (member.isfile() or member.isdir()):
            raise SystemExit(f"Type de fichier refusé dans l'archive : {member.name}")
        members.append(member)
    return members


def _extract(tar: tarfile.TarFile, root: Path, members: list[tarfile.TarInfo]) -> None:
    if hasattr(tarfile, "data_filter"):  # Python ≥ 3.12 (et correctifs 3.10.12 / 3.11.4)
        tar.extractall(root, members=members, filter="data")
    else:
        tar.extractall(root, members=members)


def restore(archive: str | os.PathLike, force: bool = False) -> None:
    archive = Path(archive)
    if not archive.is_file():
        raise SystemExit(f"Archive introuvable : {archive}")
    if _has_data() and not force:
        raise SystemExit("Des données existent déjà. Relancez avec --force pour les remplacer.")

    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()
        if MANIFEST not in names or "caffein.db" not in names:
            raise SystemExit("Ce fichier n'est pas une sauvegarde Caffein.")
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        root = config.DATA_DIR.resolve()
        members = _checked_members(tar, root)  # validé avant de toucher aux données existantes
        for suffix in ("", "-wal", "-shm"):
            path = config.DB_PATH.with_name(config.DB_PATH.name + suffix)
            if path.exists():
                path.unlink()
        for name in CONTENT_DIRS:
            shutil.rmtree(config.DATA_DIR / name, ignore_errors=True)
        _extract(tar, root, members)
    (config.DATA_DIR / MANIFEST).unlink(missing_ok=True)
    if config.KEY_FILE.exists():
        config.KEY_FILE.chmod(0o600)
    db.init_db()  # une sauvegarde plus ancienne est migrée au schéma courant
