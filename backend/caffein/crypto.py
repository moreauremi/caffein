# SPDX-License-Identifier: AGPL-3.0-or-later
"""Chiffrement AES-256-GCM des champs financiers sensibles.

Remplace crypto-js (doc §12) : le chiffrement se fait avant l'insertion en base
et le déchiffrement côté serveur, la clé ne quitte jamais la machine et n'est
plus embarquée dans le bundle JavaScript.
"""

from __future__ import annotations

import base64
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import config

PREFIX = "v1:"
_key_cache: bytes | None = None


def _load_key() -> bytes:
    global _key_cache
    if _key_cache is not None:
        return _key_cache

    env_key = os.getenv("CAFFEIN_ENCRYPTION_KEY", "").strip()
    if env_key:
        key = bytes.fromhex(env_key)
        if len(key) != 32:
            raise ValueError("CAFFEIN_ENCRYPTION_KEY doit faire 64 caractères hexadécimaux (32 octets).")
    elif config.KEY_FILE.exists():
        key = bytes.fromhex(config.KEY_FILE.read_text().strip())
    else:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        key = secrets.token_bytes(32)
        config.KEY_FILE.write_text(key.hex())
        config.KEY_FILE.chmod(0o600)

    _key_cache = key
    return key


def encrypt(value: object) -> str:
    if value is None or value == "":
        return ""
    nonce = secrets.token_bytes(12)
    data = AESGCM(_load_key()).encrypt(nonce, str(value).encode("utf-8"), None)
    return PREFIX + base64.b64encode(nonce + data).decode("ascii")


def decrypt(value: str | None) -> str:
    """Déchiffre une valeur. Valeur vide → '' ; valeur non chiffrée ou clé
    incorrecte → valeur brute (même stratégie de repli que la doc)."""
    if not value:
        return ""
    if not value.startswith(PREFIX):
        return value
    try:
        raw = base64.b64decode(value[len(PREFIX):])
        return AESGCM(_load_key()).decrypt(raw[:12], raw[12:], None).decode("utf-8")
    except Exception:
        return value


def decrypt_float(value: str | None) -> float:
    try:
        return float(decrypt(value) or 0)
    except ValueError:
        return 0.0
