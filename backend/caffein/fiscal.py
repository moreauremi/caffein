# SPDX-License-Identifier: AGPL-3.0-or-later
"""Règles fiscales : périodes TVA, cotisations URSSAF micro-entrepreneur, échéances.

⚠️ Les taux et seuils ci-dessous sont indicatifs (barème 2026) et doivent être
vérifiés chaque année sur autoentrepreneur.urssaf.fr / impots.gouv.fr.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .utils import MONTHS_FR, MONTHS_FR_SHORT, add_months, month_end

# Taux de cotisations sociales, CFP et versement libératoire, par activité
ACTIVITIES: dict[str, dict] = {
    "bic_vente": {
        "label": "Vente de marchandises (BIC)",
        "rate": 0.123, "cfp": 0.001, "vl": 0.010,
        "plafond": 203_100, "franchise_tva": 85_000,
    },
    "bic_services": {
        "label": "Prestations de services commerciales (BIC)",
        "rate": 0.212, "cfp": 0.001, "vl": 0.017,  # CFP 0,3 % pour les artisans
        "plafond": 83_600, "franchise_tva": 37_500,
    },
    "bnc": {
        "label": "Profession libérale non réglementée (BNC – SSI)",
        "rate": 0.261, "cfp": 0.002, "vl": 0.022,
        "plafond": 83_600, "franchise_tva": 37_500,
    },
    "bnc_cipav": {
        "label": "Profession libérale réglementée (BNC – Cipav)",
        "rate": 0.232, "cfp": 0.002, "vl": 0.022,
        "plafond": 83_600, "franchise_tva": 37_500,
    },
}

TVA_DEADLINE_DAY = 20  # doc §8 : « 20 du mois suivant la période »


@dataclass
class Period:
    key: str
    label: str
    start: date
    end: date

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label,
                "start": self.start.isoformat(), "end": self.end.isoformat()}


# ── TVA ──────────────────────────────────────────────────────────────────
def tva_period(kind: str, ref: date) -> Period:
    """Mois calendaire, 3 derniers mois glissants, ou année fiscale en cours."""
    if kind == "quarter":
        start = add_months(ref.replace(day=1), -2)
        return Period("quarter", f"{MONTHS_FR[start.month - 1]} – {MONTHS_FR[ref.month - 1]} {ref.year}",
                      start, month_end(ref))
    if kind == "year":
        return Period("year", str(ref.year), date(ref.year, 1, 1), date(ref.year, 12, 31))
    return Period("month", f"{MONTHS_FR[ref.month - 1]} {ref.year}", ref.replace(day=1), month_end(ref))


def tva_chart_months(kind: str, ref: date) -> list[date]:
    """Premiers jours des mois affichés dans le graphique d'évolution."""
    if kind == "year":
        return [date(ref.year, m, 1) for m in range(1, 13)]
    count = 3 if kind == "quarter" else 6
    first = add_months(ref.replace(day=1), -(count - 1))
    return [add_months(first, i) for i in range(count)]


def tva_deadline(period_end: date) -> date:
    nxt = add_months(period_end.replace(day=1), 1)
    return nxt.replace(day=TVA_DEADLINE_DAY)


def month_label_short(d: date) -> str:
    return f"{MONTHS_FR_SHORT[d.month - 1]} {str(d.year)[2:]}"


# ── URSSAF ───────────────────────────────────────────────────────────────
def activity_info(activity: str) -> dict:
    return ACTIVITIES.get(activity, ACTIVITIES["bnc"])


def contribution_rate(activity: str, versement_liberatoire: bool) -> float:
    info = activity_info(activity)
    return info["rate"] + info["cfp"] + (info["vl"] if versement_liberatoire else 0.0)


def declaration_periods(year: int, frequency: str) -> list[Period]:
    if frequency == "quarterly":
        periods = []
        for q in range(4):
            start = date(year, q * 3 + 1, 1)
            periods.append(Period(f"{year}-T{q + 1}", f"{q + 1}ᵉ trimestre {year}", start, month_end(add_months(start, 2))))
        return periods
    return [
        Period(f"{year}-{m:02d}", f"{MONTHS_FR[m - 1].capitalize()} {year}", date(year, m, 1), month_end(date(year, m, 1)))
        for m in range(1, 13)
    ]


def declaration_deadline(period: Period) -> date:
    """Dernier jour du mois qui suit la période : en mensuel le mois suivant,
    en trimestriel 30/04, 31/07, 31/10 et 31/01."""
    return month_end(add_months(period.end.replace(day=1), 1))


def declaration_status(period: Period, deadline: date, declared: bool, ref: date, tracked_from: date | None = None) -> str:
    if declared:
        return "declared"
    if tracked_from and deadline < tracked_from:
        return "untracked"  # échéance antérieure à l'installation de Caffein
    if period.end >= ref:
        return "in_progress" if period.start <= ref else "upcoming"
    if deadline >= ref:
        return "to_declare"
    return "late"


def days_between(a: date, b: date) -> int:
    return (b - a).days


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())
