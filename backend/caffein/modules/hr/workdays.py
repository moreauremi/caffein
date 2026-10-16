# SPDX-License-Identifier: AGPL-3.0-or-later
"""Jours ouvrés et jours fériés français, calculés en Python.

Un jour ouvré va du lundi au vendredi, hors jours fériés : 1er janvier, lundi de Pâques, 1er mai, 8 mai,
Ascension (Pâques + 39 jours), lundi de Pentecôte (Pâques + 50 jours), 14 juillet, 15 août, 1er novembre,
11 novembre et 25 décembre. La date de Pâques suit l'algorithme grégorien anonyme (Meeus, Jones, Butcher).
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

from ...utils import parse_date


def easter(year: int) -> date:
    """Dimanche de Pâques de l'année (calendrier grégorien)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    weekday_shift = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * weekday_shift) // 451
    month, day = divmod(h + weekday_shift - 7 * m + 114, 31)
    return date(year, month, day + 1)


@lru_cache(maxsize=512)
def _holidays(year: int) -> tuple[tuple[date, tuple[str, str]], ...]:
    sunday = easter(year)
    return (
        (date(year, 1, 1), ("Jour de l'an", "New Year's Day")),
        (sunday + timedelta(days=1), ("Lundi de Pâques", "Easter Monday")),
        (date(year, 5, 1), ("Fête du Travail", "Labour Day")),
        (date(year, 5, 8), ("Victoire 1945", "Victory in Europe Day")),
        (sunday + timedelta(days=39), ("Ascension", "Ascension Day")),
        (sunday + timedelta(days=50), ("Lundi de Pentecôte", "Whit Monday")),
        (date(year, 7, 14), ("Fête nationale", "Bastille Day")),
        (date(year, 8, 15), ("Assomption", "Assumption Day")),
        (date(year, 11, 1), ("Toussaint", "All Saints' Day")),
        (date(year, 11, 11), ("Armistice 1918", "Armistice Day")),
        (date(year, 12, 25), ("Noël", "Christmas Day")),
    )


def public_holidays(year: int) -> dict[date, tuple[str, str]]:
    """Jours fériés de l'année : {date: (nom français, nom anglais)}."""
    return dict(_holidays(year))


def is_working_day(day: date) -> bool:
    return day.weekday() < 5 and all(holiday != day for holiday, _ in _holidays(day.year))


def working_days(start: date | str | None, end: date | str | None) -> int:
    """Jours ouvrés entre deux dates incluses ; 0 si une date manque ou si la période est vide."""
    first, last = parse_date(start), parse_date(end)
    if first is None or last is None or last < first:
        return 0
    weeks, rest = divmod((last - first).days + 1, 7)
    count = weeks * 5 + sum(1 for offset in range(rest) if (first + timedelta(days=weeks * 7 + offset)).weekday() < 5)
    for year in range(first.year, last.year + 1):
        count -= sum(1 for holiday, _ in _holidays(year) if first <= holiday <= last and holiday.weekday() < 5)
    return count


def next_working_day(day: date) -> date:
    """Le jour même s'il est ouvré, sinon le premier jour ouvré qui suit."""
    while not is_working_day(day):
        day += timedelta(days=1)
    return day
