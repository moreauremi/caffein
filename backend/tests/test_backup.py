# SPDX-License-Identifier: AGPL-3.0-or-later
import tarfile

import pytest

from caffein import backup, db, services


def test_backup_and_restore_roundtrip(demo, tmp_path):
    before = len(services.list_invoices())
    archive = backup.backup(tmp_path / "save.tar.gz")
    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert {"caffein-backup.json", "caffein.db", ".encryption_key"} <= set(names)

    db.execute("DELETE FROM emails")
    db.execute("DELETE FROM invoices")
    with pytest.raises(SystemExit):
        backup.restore(archive)  # des données existent : --force requis
    backup.restore(archive, force=True)
    assert len(services.list_invoices()) == before
    assert services.list_documents()[0]["fournisseur"]  # déchiffrement toujours possible


def test_restore_rejects_path_traversal(demo, tmp_path):
    evil = tmp_path / "evil.tar.gz"
    payload = tmp_path / "x.txt"
    payload.write_text("x")
    with tarfile.open(evil, "w:gz") as tar:
        tar.add(payload, arcname="caffein-backup.json")
        tar.add(payload, arcname="caffein.db")
        tar.add(payload, arcname="../../evil.txt")
    with pytest.raises(SystemExit):
        backup.restore(evil, force=True)
    assert services.list_invoices()  # rien n'a été effacé
