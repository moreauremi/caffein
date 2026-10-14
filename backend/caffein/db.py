# SPDX-License-Identifier: AGPL-3.0-or-later
"""Base SQLite locale (remplace Supabase PostgreSQL) et migrations de schéma."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from . import config

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    full_name TEXT NOT NULL DEFAULT '',
    company TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    zip_code TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    siret TEXT NOT NULL DEFAULT '',
    naf_code TEXT NOT NULL DEFAULT '',
    iban TEXT NOT NULL DEFAULT '',
    bic TEXT NOT NULL DEFAULT '',
    legal_mention TEXT NOT NULL DEFAULT 'Entrepreneur individuel (EI)',
    activity TEXT NOT NULL DEFAULT 'bnc',
    declaration_frequency TEXT NOT NULL DEFAULT 'monthly',
    versement_liberatoire INTEGER NOT NULL DEFAULT 0,
    vat_exempt INTEGER NOT NULL DEFAULT 0,
    vat_number TEXT NOT NULL DEFAULT '',
    default_vat_rate REAL NOT NULL DEFAULT 0.20,
    payment_terms_days INTEGER NOT NULL DEFAULT 30,
    invoice_prefix TEXT NOT NULL DEFAULT 'CAFFEIN',
    notif_tva INTEGER NOT NULL DEFAULT 1,
    notif_echeance INTEGER NOT NULL DEFAULT 1,
    notif_hebdo INTEGER NOT NULL DEFAULT 1,
    tva_alert_threshold REAL NOT NULL DEFAULT 1000,
    newsletter INTEGER NOT NULL DEFAULT 0,
    onboarding_step INTEGER NOT NULL DEFAULT 0,
    onboarding_done INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    contact_name TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    zip_code TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    siren TEXT NOT NULL DEFAULT '',
    vat_number TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

-- Factures et devis émis par le freelance
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL DEFAULT 'invoice' CHECK (kind IN ('invoice', 'quote')),
    number TEXT UNIQUE,
    public_token TEXT NOT NULL UNIQUE,
    client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
    title TEXT NOT NULL DEFAULT '',
    items TEXT NOT NULL DEFAULT '[]',
    vat_exempt INTEGER NOT NULL DEFAULT 0,
    vat_rate REAL NOT NULL DEFAULT 0.20,
    subtotal REAL NOT NULL DEFAULT 0,
    vat_amount REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL DEFAULT 0,
    issued_at TEXT,
    due_date TEXT,
    delivery_date TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    paid_at TEXT,
    emailed_at TEXT,
    emailed_to TEXT,
    pdf_path TEXT,
    reminder_count INTEGER NOT NULL DEFAULT 0,
    last_reminder_at TEXT,
    last_reminder_tone TEXT,
    notes TEXT NOT NULL DEFAULT '',
    payment_conditions TEXT NOT NULL DEFAULT '',
    source_quote_id INTEGER REFERENCES invoices(id) ON DELETE SET NULL,
    source_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Documents classés par l'IA (ex-table « factures » Supabase).
-- Les champs sensibles sont chiffrés en AES-256-GCM.
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT,
    fournisseur TEXT NOT NULL DEFAULT '',
    ht TEXT NOT NULL DEFAULT '',
    tva TEXT NOT NULL DEFAULT '',
    ttc TEXT NOT NULL DEFAULT '',
    categorie TEXT NOT NULL DEFAULT '',
    resume TEXT NOT NULL DEFAULT '',
    tva_type TEXT NOT NULL CHECK (tva_type IN ('collected', 'deductible')),
    echeance TEXT,
    file_path TEXT,
    original_name TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'inbox',
    invoice_id INTEGER REFERENCES invoices(id) ON DELETE CASCADE,
    extracted_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

-- Actualités affichées sur l'accueil (ex-table notification_caffein)
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    tag TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '#E3F2FD',
    tag_color TEXT NOT NULL DEFAULT '#1565C0',
    created_at TEXT NOT NULL
);

-- Journal de tous les emails (envoyés via Resend ou simulés)
CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    to_email TEXT NOT NULL,
    from_email TEXT NOT NULL DEFAULT '',
    subject TEXT NOT NULL,
    html TEXT NOT NULL,
    attachment_name TEXT,
    status TEXT NOT NULL,
    provider_id TEXT,
    error TEXT,
    invoice_id INTEGER REFERENCES invoices(id) ON DELETE SET NULL,
    meta TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

-- Historique d'exécution des scripts (remplace les « executions » n8n)
CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job TEXT NOT NULL,
    trigger TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    details TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS declarations (
    period_key TEXT PRIMARY KEY,
    declared_at TEXT NOT NULL
);

-- Alertes déjà envoyées (évite les doublons des alertes fiscales)
CREATE TABLE IF NOT EXISTS alerts_sent (
    key TEXT PRIMARY KEY,
    sent_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(kind, status);
CREATE INDEX IF NOT EXISTS idx_documents_date ON documents(date);
CREATE INDEX IF NOT EXISTS idx_job_runs_job ON job_runs(job, started_at);
"""


# Version 2 : comptes utilisateurs, sessions, auteur des exécutions, emails de prise en main
SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member')),
    active INTEGER NOT NULL DEFAULT 1,
    is_demo INTEGER NOT NULL DEFAULT 0,
    last_login_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    ip TEXT NOT NULL DEFAULT '',
    user_agent TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

ALTER TABLE job_runs ADD COLUMN actor TEXT;
ALTER TABLE profile ADD COLUMN notif_onboarding INTEGER NOT NULL DEFAULT 1;
"""

# Version 3 : vues du tableau de bord à la demande (« Mes vues »), propres à chaque utilisateur
SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS dashboard_views (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    spec TEXT NOT NULL DEFAULT '{}',
    prompt TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dashboard_views_user ON dashboard_views(user_id);
"""

# Version 4 : architecture modulaire (docs/modules.md).
# - modules : activation de chaque module ; schema_migrations : versions appliquées des modules ;
# - rôles, droits par module et dérogations par utilisateur ;
# - lignes des factures et devis dans une table (elles étaient dans le champ JSON invoices.items).
SCHEMA_V4 = """
CREATE TABLE IF NOT EXISTS modules (
    key TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    settings TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    module TEXT NOT NULL,
    version INTEGER NOT NULL,
    applied_at TEXT NOT NULL,
    PRIMARY KEY (module, version)
);

CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT NOT NULL DEFAULT '',
    default_level INTEGER NOT NULL DEFAULT 0 CHECK (default_level BETWEEN 0 AND 3),
    is_system INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id INTEGER NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    module TEXT NOT NULL,
    level INTEGER NOT NULL CHECK (level BETWEEN 0 AND 3),
    PRIMARY KEY (role_id, module)
);

CREATE TABLE IF NOT EXISTS user_permissions (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    module TEXT NOT NULL,
    level INTEGER NOT NULL CHECK (level BETWEEN 0 AND 3),
    PRIMARY KEY (user_id, module)
);

ALTER TABLE users ADD COLUMN role_id INTEGER REFERENCES roles(id) ON DELETE SET NULL;

-- Rôles fournis. « Équipe » reprend les droits des membres d'avant les modules (tout, sauf les paramètres).
INSERT INTO roles (key, name, description, default_level, is_system, created_at) VALUES
    ('team', 'Équipe (accès complet)', 'Lecture et écriture sur tous les modules actifs.', 2, 1, strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    ('readonly', 'Lecture seule', 'Consulte tous les modules actifs, sans rien modifier.', 1, 1, strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    ('sales', 'Commercial', 'Ventes et CRM ; consulte les articles et les stocks.', 0, 0, strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    ('buyer', 'Acheteur', 'Achats ; consulte les articles et les stocks.', 0, 0, strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    ('production', 'Production', 'Production, données techniques et stocks.', 0, 0, strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    ('hr', 'Ressources humaines', 'RH, y compris les données sensibles (salaires).', 0, 0, strftime('%Y-%m-%dT%H:%M:%S', 'now')),
    ('accountant', 'Comptable', 'Comptabilité ; consulte les ventes et les achats.', 0, 0, strftime('%Y-%m-%dT%H:%M:%S', 'now'));

INSERT INTO role_permissions (role_id, module, level)
    SELECT r.id, p.module, p.level FROM roles r JOIN (
        SELECT 'sales' AS role, 'sales' AS module, 2 AS level UNION ALL SELECT 'sales', 'crm', 2
        UNION ALL SELECT 'sales', 'technical', 1 UNION ALL SELECT 'sales', 'stock', 1
        UNION ALL SELECT 'buyer', 'purchases', 2 UNION ALL SELECT 'buyer', 'technical', 1 UNION ALL SELECT 'buyer', 'stock', 1
        UNION ALL SELECT 'production', 'production', 2 UNION ALL SELECT 'production', 'technical', 2
        UNION ALL SELECT 'production', 'stock', 2
        UNION ALL SELECT 'hr', 'hr', 3
        UNION ALL SELECT 'accountant', 'accounting', 2 UNION ALL SELECT 'accountant', 'sales', 1
        UNION ALL SELECT 'accountant', 'purchases', 1
    ) p ON p.role = r.key;

UPDATE users SET role_id = (SELECT id FROM roles WHERE key = 'team') WHERE role = 'member';

-- Lignes des factures et devis. article_id : article des Données techniques, facultatif (sans clé
-- étrangère : le module peut être absent ou désactivé).
CREATE TABLE IF NOT EXISTS invoice_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    article_id INTEGER,
    description TEXT NOT NULL DEFAULT '',
    quantity REAL NOT NULL DEFAULT 1,
    unit_price REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_invoice_lines_invoice ON invoice_lines(invoice_id, position);

INSERT INTO invoice_lines (invoice_id, position, description, quantity, unit_price)
    SELECT i.id, CAST(j.key AS INTEGER), COALESCE(json_extract(j.value, '$.description'), ''),
           COALESCE(json_extract(j.value, '$.quantity'), 1), COALESCE(json_extract(j.value, '$.unit_price'), 0)
    FROM invoices i, json_each(i.items) j
    WHERE json_valid(i.items) AND json_type(i.items) = 'array';
UPDATE invoices SET items = '[]';
"""

# Chaque migration est appliquée une seule fois, dans l'ordre (PRAGMA user_version).
# Pour faire évoluer le schéma : ajoutez une entrée, ne modifiez jamais une migration publiée.
# Les tables des modules ont leurs propres migrations (core/migrations.py).
MIGRATIONS: list[tuple[int, str]] = [(1, SCHEMA_V1), (2, SCHEMA_V2), (3, SCHEMA_V3), (4, SCHEMA_V4)]
SCHEMA_VERSION = MIGRATIONS[-1][0]


def now_iso() -> str:
    return datetime.now(config.TIMEZONE).replace(microsecond=0).isoformat()


def _dict_factory(cursor: sqlite3.Cursor, row: tuple) -> dict[str, Any]:
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=15)
    conn.row_factory = _dict_factory
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def schema_version() -> int:
    with connect() as conn:
        return conn.execute("PRAGMA user_version").fetchone()["user_version"]


def init_db() -> None:
    """Crée la base si besoin et applique les migrations manquantes."""
    config.ensure_dirs()
    with connect() as conn:
        current = conn.execute("PRAGMA user_version").fetchone()["user_version"]
        for version, script in MIGRATIONS:
            if version <= current:
                continue
            conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {version};\nCOMMIT;")
    # Puis les tables des modules (import local : les modules importent db)
    from .core import migrations

    migrations.apply_all()


def fetch_all(sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
    with connect() as conn:
        return conn.execute(sql, params).fetchall()


def fetch_one(sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
    with connect() as conn:
        return conn.execute(sql, params).fetchone()


def execute(sql: str, params: tuple | dict = ()) -> int:
    """Exécute une requête d'écriture et renvoie lastrowid."""
    with connect() as conn:
        cur = conn.execute(sql, params)
        return cur.lastrowid


def insert(table: str, values: dict[str, Any]) -> int:
    cols = ", ".join(values)
    marks = ", ".join(f":{k}" for k in values)
    return execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", values)


def update(table: str, row_id: int, values: dict[str, Any]) -> None:
    if not values:
        return
    sets = ", ".join(f"{k} = :{k}" for k in values)
    execute(f"UPDATE {table} SET {sets} WHERE id = :_id", {**values, "_id": row_id})


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default
