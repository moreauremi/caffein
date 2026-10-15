# SPDX-License-Identifier: AGPL-3.0-or-later
"""Chiffres des Projets, calculés en Python (jamais stockés : ils suivent les temps saisis) :

- heures passées d'un projet ou d'une tâche : somme des temps saisis, facturables ou non ;
- temps à facturer : temps facturables sans facture valable, c'est-à-dire jamais facturés, ou dont la facture
  brouillon a été supprimée ou la facture annulée dans les Ventes ;
- lignes de facture : une par tâche, dans l'ordre de leur premier temps saisi, puis « Temps passé » pour les temps
  sans tâche ; quantité = heures de la ligne ;
- montant à facturer : heures de chaque ligne × taux horaire, arrondi au centime ligne par ligne, comme la facture
  que « Facturer les temps » créera ;
- heures arrondies au centième, la moitié vers le haut (1,005 → 1,01), comme les montants.

Les écrans (fiche, liste, aperçu de saisie, vue en colonnes), les chiffres clés et la facturation des temps
s'appuient tous sur ces fonctions.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from ... import db
from ...core import modules as registry
from ...utils import cents

NO_TASK = "Temps passé"  # ligne de facture des temps saisis sans tâche


def hours(value: float | int | None) -> float:
    """Heures arrondies au centième, la moitié vers le haut."""
    return cents(value or 0)


def hours_text(value: float | int | None) -> str:
    """12.5 → « 12,5 » ; 3.0 → « 3 » (messages en français)."""
    return f"{hours(value):.2f}".rstrip("0").rstrip(".").replace(".", ",")


def percent(part: float, whole: float | None) -> float | None:
    """Part en pourcentage, au dixième (la moitié vers le haut) ; None sans total."""
    if not whole or whole <= 0:
        return None
    return float(Decimal(repr(part / whole * 100)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _ids(values) -> list[int]:
    return sorted({v for v in values if isinstance(v, int) and not isinstance(v, bool)})


def _marks(ids: list) -> str:
    return ", ".join("?" for _ in ids)


# ═════════════════════════════════════════════════════════════════════════
# Factures des Ventes : un temps est facturé tant que sa facture existe et n'est pas annulée
# ═════════════════════════════════════════════════════════════════════════
def open_condition(column: str) -> str:
    """Condition SQL « pas encore facturé » sur la colonne `invoice_id` d'un temps (nom écrit dans le code).
    Sans les Ventes, la facture ne peut pas être vérifiée : un temps rattaché à une facture reste facturé."""
    if registry.is_enabled("sales"):
        return (f"({column} IS NULL OR NOT EXISTS (SELECT 1 FROM invoices inv WHERE inv.id = {column} "
                f"AND inv.status != 'cancelled'))")
    return f"{column} IS NULL"


def invoice_states(invoice_ids) -> dict[int, dict]:
    """{facture: {"valid": la facture existe et n'est pas annulée, "number": numéro, « brouillon », ou "" si inconnu}}."""
    ids = _ids(invoice_ids)
    if not ids:
        return {}
    if not registry.is_enabled("sales"):
        return {i: {"valid": True, "number": ""} for i in ids}
    found = {r["id"]: r for r in db.fetch_all(f"SELECT id, number, status FROM invoices WHERE id IN ({_marks(ids)})",
                                              tuple(ids))}
    out = {}
    for invoice_id in ids:
        row = found.get(invoice_id)
        valid = row is not None and row["status"] != "cancelled"
        out[invoice_id] = {"valid": valid, "number": (row["number"] or "brouillon") if valid else ""}
    return out


# ═════════════════════════════════════════════════════════════════════════
# Heures passées, tâches ouvertes, taux
# ═════════════════════════════════════════════════════════════════════════
_GROUPS = {"project_id", "task_id"}


def hours_by(column: str, ids) -> dict[int, float]:
    """Heures saisies par projet (`project_id`) ou par tâche (`task_id`), en une requête groupée."""
    if column not in _GROUPS:
        raise ValueError(f"Regroupement inconnu : {column!r}")
    keys = _ids(ids)
    if not keys:
        return {}
    rows = db.fetch_all(f"SELECT {column} AS k, SUM(hours) AS h FROM projects_timesheets WHERE {column} IN ({_marks(keys)}) "
                        f"GROUP BY {column}", tuple(keys))
    return {r["k"]: hours(r["h"]) for r in rows}


def open_tasks(project_ids) -> dict[int, int]:
    """Tâches pas encore terminées de chaque projet."""
    ids = _ids(project_ids)
    if not ids:
        return {}
    rows = db.fetch_all(f"SELECT project_id, COUNT(*) AS n FROM projects_tasks WHERE status != 'done' "
                        f"AND project_id IN ({_marks(ids)}) GROUP BY project_id", tuple(ids))
    return {r["project_id"]: r["n"] for r in rows}


def project_rates(project_ids) -> dict[int, float | None]:
    """Taux horaire facturé de chaque projet."""
    ids = _ids(project_ids)
    if not ids:
        return {}
    rows = db.fetch_all(f"SELECT id, hourly_rate FROM projects_projects WHERE id IN ({_marks(ids)})", tuple(ids))
    return {r["id"]: r["hourly_rate"] for r in rows}


def hours_between(start: date, end: date) -> tuple[float, int]:
    """Heures saisies et nombre de temps datés de `start` inclus à `end` exclu."""
    row = db.fetch_one("SELECT COALESCE(SUM(hours), 0) AS h, COUNT(*) AS n FROM projects_timesheets "
                       "WHERE date >= ? AND date < ?", (start.isoformat(), end.isoformat()))
    return hours(row["h"]), row["n"]


# ═════════════════════════════════════════════════════════════════════════
# Temps à facturer
# ═════════════════════════════════════════════════════════════════════════
def unbilled_entries(project_ids=None) -> list[dict]:
    """Temps facturables pas encore facturés, par date (tous les projets si `project_ids` est None)."""
    where = ["t.billable = 1", "t.hours > 0", "t.project_id IS NOT NULL", open_condition("t.invoice_id")]
    params: list = []
    if project_ids is not None:
        ids = _ids(project_ids)
        if not ids:
            return []
        where.append(f"t.project_id IN ({_marks(ids)})")
        params += ids
    return db.fetch_all(
        f"SELECT t.id, t.project_id, t.task_id, k.title AS task_title, t.date, t.hours FROM projects_timesheets t "
        f"LEFT JOIN projects_tasks k ON k.id = t.task_id WHERE {' AND '.join(where)} ORDER BY t.date, t.id", tuple(params))


def billing_lines(entries: list[dict]) -> dict[int, list[dict]]:
    """Temps à facturer → lignes de facture de chaque projet : une par tâche, dans l'ordre de leur premier temps saisi,
    puis une ligne pour les temps sans tâche. Chaque ligne porte ses heures et les temps qu'elle reprend."""
    projects: dict[int, dict] = {}
    for entry in sorted(entries, key=lambda e: (e["date"] or "", e["id"])):
        lines = projects.setdefault(entry["project_id"], {})
        line = lines.setdefault(entry["task_id"], {
            "task_id": entry["task_id"], "title": entry.get("task_title") or "", "hours": 0.0,
            "first_date": entry["date"], "last_date": entry["date"], "entries": [],
        })
        line["hours"] += entry["hours"] or 0
        line["last_date"] = max(line["last_date"] or "", entry["date"] or "") or None
        line["entries"].append(entry["id"])
    out = {}
    for project_id, lines in projects.items():
        ordered = sorted(lines.values(), key=lambda line: line["task_id"] is None)  # tri stable : sans tâche en dernier
        for line in ordered:
            line["hours"] = hours(line["hours"])
        out[project_id] = ordered
    return out


def line_description(line: dict) -> str:
    return f"Tâche : {line['title']}" if line["task_id"] else NO_TASK


def amount(lines: list[dict], rate: float | None) -> float:
    """Montant HT des lignes : heures × taux, arrondi au centime ligne par ligne, comme sur la facture."""
    if not rate or rate <= 0:
        return 0.0
    return cents(sum(cents(line["hours"] * rate) for line in lines))


def to_invoice_summary() -> dict:
    """Montant HT du temps à facturer sur tous les projets, et nombre de projets concernés."""
    lines = billing_lines(unbilled_entries())
    rates = project_rates(list(lines))
    total = sum(amount(project_lines, rates.get(project_id)) for project_id, project_lines in lines.items())
    return {"amount": cents(total), "projects": len(lines)}
