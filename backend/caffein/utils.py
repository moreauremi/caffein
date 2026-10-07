# SPDX-License-Identifier: AGPL-3.0-or-later
"""Petits utilitaires partagés : dates, formats français, noms de fichiers."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

from . import config

MONTHS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]
MONTHS_FR_SHORT = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
                   "juil.", "août", "sept.", "oct.", "nov.", "déc."]

NBSP = " "


def today() -> date:
    return datetime.now(config.TIMEZONE).date()


def parse_date(value: object) -> date | None:
    """Accepte date, datetime, 'AAAA-MM-JJ[ HH:MM:SS]', 'JJ/MM/AAAA'."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})$", text)
    if m:
        year = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
        try:
            return date(year, int(m[2]), int(m[1]))
        except ValueError:
            return None
    return None


def iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def fmt_money(amount: float | None, currency: str = "€") -> str:
    """1234.5 → '1 234,50 €' (espaces insécables, compatibles PDF WinAnsi)."""
    value = float(amount or 0)
    sign = "-" if value < 0 else ""
    integer, decimals = f"{abs(value):.2f}".split(".")
    groups = []
    while integer:
        groups.insert(0, integer[-3:])
        integer = integer[:-3]
    return f"{sign}{NBSP.join(groups)},{decimals}{NBSP}{currency}"


def fmt_date(value: object) -> str:
    d = parse_date(value)
    return d.strftime("%d/%m/%Y") if d else ""


def fmt_date_long(value: object) -> str:
    d = parse_date(value)
    return f"{d.day:02d} {MONTHS_FR[d.month - 1]} {d.year}" if d else ""


def add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    last_day = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(d.day, last_day))


def month_end(d: date) -> date:
    return add_months(d.replace(day=1), 1) - timedelta(days=1)


def slugify_name(text: str, fallback: str = "INCONNU") -> str:
    """Nom de dossier/fichier sûr : 'Adobe Systems, Inc.' → 'ADOBE SYSTEMS INC'."""
    norm = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    norm = re.sub(r"[^A-Za-z0-9&' -]+", " ", norm).strip().upper()
    norm = re.sub(r"\s+", " ", norm)
    return norm[:60] or fallback


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for i in range(2, 1000):
        candidate = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Impossible de trouver un nom libre pour {path}")


def to_float(value: object) -> float | None:
    """'1 234,56 €' / '1234.56' / 1234.56 → 1234.56 ; None si illisible."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[^\d,.\-]", "", str(value))
    if not text:
        return None
    if "," in text and "." in text:
        # le dernier séparateur est le séparateur décimal
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None
