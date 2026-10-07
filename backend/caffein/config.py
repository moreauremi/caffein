# SPDX-License-Identifier: AGPL-3.0-or-later
"""Configuration centrale de Caffein (chemins, variables d'environnement, constantes).

Ordre de chargement des variables : environnement du processus, puis le fichier
désigné par CAFFEIN_ENV_FILE (installation Linux : /etc/caffein/caffein.env),
puis <racine du projet>/.env. Une variable déjà définie n'est jamais écrasée.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# racine du projet — backend/caffein/config.py → parents[2]
ROOT_DIR = Path(__file__).resolve().parents[2]
if os.getenv("CAFFEIN_ENV_FILE"):
    load_dotenv(os.environ["CAFFEIN_ENV_FILE"])
load_dotenv(ROOT_DIR / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


# ── Chemins ──────────────────────────────────────────────────────────────
DATA_DIR = Path(os.getenv("CAFFEIN_DATA_DIR") or ROOT_DIR / "data").resolve()
DB_PATH = DATA_DIR / "caffein.db"
OUTBOX_DIR = DATA_DIR / "outbox"
KEY_FILE = DATA_DIR / ".encryption_key"
FRONTEND_DIST = Path(os.getenv("CAFFEIN_FRONTEND_DIST") or ROOT_DIR / "frontend" / "dist").resolve()

# Arborescence de classement (remplace Google Drive)
DRIVE_DIR = DATA_DIR / "drive" / "Caffein"
FOLDERS = {
    "a_traiter": DRIVE_DIR / "Factures à traiter",
    "factures": DRIVE_DIR / "Factures",
    "envoyees": DRIVE_DIR / "Factures" / "Factures envoyées",
    "recues": DRIVE_DIR / "Factures" / "Factures reçues",
    "contrats": DRIVE_DIR / "Contrats",
    "recus": DRIVE_DIR / "Reçus",
    "ne_pas_trier": DRIVE_DIR / "Ne pas trier",
}
INBOX_DIR = FOLDERS["a_traiter"]

# ── Serveur ──────────────────────────────────────────────────────────────
HOST = os.getenv("CAFFEIN_HOST") or "127.0.0.1"
PORT = _env_int("CAFFEIN_PORT", 8000)
APP_URL = (os.getenv("CAFFEIN_APP_URL") or f"http://localhost:{PORT}").rstrip("/")
TIMEZONE = ZoneInfo(os.getenv("CAFFEIN_TIMEZONE") or "Europe/Paris")
SCHEDULER_ENABLED = _env_bool("CAFFEIN_SCHEDULER", True)

# Mode démonstration : données d'exemple + bouton « Accès démo » sans mot de passe.
# À n'utiliser que pour une instance de présentation publique ou en local.
DEMO_MODE = _env_bool("CAFFEIN_DEMO", False)

# ── Sécurité ─────────────────────────────────────────────────────────────
SESSION_DAYS = _env_int("CAFFEIN_SESSION_DAYS", 14)
SECURE_COOKIES = _env_bool("CAFFEIN_SECURE_COOKIES", urlparse(APP_URL).scheme == "https")
LOGIN_MAX_FAILURES = 5        # tentatives par adresse IP…
LOGIN_WINDOW_SECONDS = 300    # …sur 5 minutes
PASSWORD_MIN_LENGTH = 8

# AGPL-3.0, section 13 : les utilisateurs d'une version modifiée accessible par le
# réseau doivent pouvoir obtenir son code source. Par défaut : le dépôt officiel ;
# une version modifiée doit pointer vers son propre dépôt.
UPSTREAM_URL = "https://github.com/moreauremi/caffein"
SOURCE_URL = os.getenv("CAFFEIN_SOURCE_URL") or UPSTREAM_URL
LICENSE = "AGPL-3.0-or-later"

# ── IA (Claude) ──────────────────────────────────────────────────────────
# Sans clé, Caffein bascule sur des heuristiques locales (mode hors-ligne).
AI_MODEL = os.getenv("CAFFEIN_AI_MODEL") or "claude-opus-5-5"
AI_ENABLED = _env_bool(
    "CAFFEIN_AI",
    bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")),
)

# ── Emails : SMTP (recommandé en auto-hébergement) ou API Resend ─────────
# Sans l'un ni l'autre, les emails sont « simulés » : enregistrés dans la boîte d'envoi.
SMTP_HOST = os.getenv("CAFFEIN_SMTP_HOST") or ""
SMTP_PORT = _env_int("CAFFEIN_SMTP_PORT", 587)
SMTP_USER = os.getenv("CAFFEIN_SMTP_USER", "")
SMTP_PASSWORD = os.getenv("CAFFEIN_SMTP_PASSWORD", "")
SMTP_SECURITY = (os.getenv("CAFFEIN_SMTP_SECURITY") or "starttls").lower()  # starttls | ssl | none
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM_ADDRESS = os.getenv("CAFFEIN_EMAIL_FROM") or "caffein@localhost"
EMAIL_FROM_NAME = os.getenv("CAFFEIN_EMAIL_FROM_NAME") or "Caffein"

# ── Relances ─────────────────────────────────────────────────────────────
REMINDER_INTERVAL_DAYS = _env_int("CAFFEIN_REMINDER_INTERVAL_DAYS", 7)
REMINDER_MAX = 3

# ── Newsletter → actualités (IMAP optionnel, remplace le Gmail Trigger) ─
IMAP_HOST = os.getenv("CAFFEIN_IMAP_HOST", "")
IMAP_USER = os.getenv("CAFFEIN_IMAP_USER", "")
IMAP_PASSWORD = os.getenv("CAFFEIN_IMAP_PASSWORD", "")
NEWSLETTER_SENDER = os.getenv("CAFFEIN_NEWSLETTER_SENDER", "")
NOTIFICATIONS_KEPT = 4

# Temps économisé estimé (minutes) — base doc : 2 min par document classé
MINUTES_PER_DOCUMENT = 2
MINUTES_PER_INVOICE = 10
MINUTES_PER_REMINDER = 5


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    for folder in FOLDERS.values():
        folder.mkdir(parents=True, exist_ok=True)
