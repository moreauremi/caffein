# SPDX-License-Identifier: AGPL-3.0-or-later
"""Chiffres des Achats, calculés en Python (jamais stockés : ils suivent les lignes) :

- montant HT d'une ligne : quantité × prix unitaire, arrondi au centime ;
- TVA d'une commande : somme, ligne par ligne, de montant HT × taux arrondi au centime ;
- retard : commande envoyée dont la livraison prévue est passée ;
- montant HT commandé sur une période (commandes envoyées ou reçues, selon leur date de commande).

Les écrans (fiche, liste, aperçu de saisie), les fournisseurs et les chiffres clés s'appuient tous sur ces fonctions.
"""

from __future__ import annotations

from datetime import date

from ... import db
from ...utils import cents, today

PLACED = ("sent", "received")  # commandes passées au fournisseur : elles comptent dans les achats

# Valeurs par défaut d'une ligne : celles des champs (entities.py) et celles de l'aperçu d'une saisie incomplète
LINE_DEFAULTS = {"quantity": 1.0, "unit_price": 0.0, "vat_rate": 20.0}


def _number(line: dict, name: str) -> float:
    value = line.get(name, LINE_DEFAULTS[name])
    return float(value) if value is not None else 0.0


def line_amount(line: dict) -> float:
    """Montant HT d'une ligne, arrondi au centime."""
    return cents(_number(line, "quantity") * _number(line, "unit_price"))


def totals(lines: list[dict], annotate: bool = False) -> dict:
    """Montants HT, TVA et TTC d'une commande. `annotate` ajoute le montant HT de chaque ligne (fiche, aperçu)."""
    ht = vat = 0.0
    for line in lines:
        amount = line_amount(line)
        if annotate:
            line["amount"] = amount
        ht += amount
        vat += cents(amount * _number(line, "vat_rate") / 100)
    ht, vat = cents(ht), cents(vat)
    return {"total_ht": ht, "total_vat": vat, "total_ttc": cents(ht + vat)}


def is_late(order: dict) -> bool:
    """Commande envoyée dont la date de livraison prévue est passée."""
    expected = order.get("expected_date")
    return order.get("status") == "sent" and bool(expected) and str(expected) < today().isoformat()


def _marks(ids: list) -> str:
    return ", ".join("?" for _ in ids)


def lines_by_order(order_ids: list[int]) -> dict[int, list[dict]]:
    """Lignes enregistrées de plusieurs commandes, en une seule requête (listes)."""
    ids = sorted({i for i in order_ids if i})
    out: dict[int, list[dict]] = {i: [] for i in ids}
    if ids:
        for line in db.fetch_all(f"SELECT order_id, quantity, unit_price, vat_rate FROM purchases_order_lines "
                                 f"WHERE order_id IN ({_marks(ids)}) ORDER BY position, id", tuple(ids)):
            out[line["order_id"]].append(line)
    return out


def placed_between(start: date, end: date, supplier_ids: list[int] | None = None) -> dict[int, dict]:
    """Commandes passées (envoyées ou reçues) datées de `start` inclus à `end` exclu, par fournisseur :
    {fournisseur: {"count": nombre de commandes, "total_ht": montant HT}}. Tous les fournisseurs si `supplier_ids` est None."""
    where = "o.status IN (?, ?) AND o.order_date >= ? AND o.order_date < ?"
    params: list = [*PLACED, start.isoformat(), end.isoformat()]
    if supplier_ids is not None:
        if not supplier_ids:
            return {}
        where += f" AND o.supplier_id IN ({_marks(supplier_ids)})"
        params += list(supplier_ids)
    out: dict[int, dict] = {}
    for row in db.fetch_all(f"SELECT o.supplier_id, COUNT(*) AS n FROM purchases_orders o WHERE {where} GROUP BY o.supplier_id",
                            tuple(params)):
        out[row["supplier_id"]] = {"count": row["n"], "total_ht": 0.0}
    for line in db.fetch_all(f"SELECT o.supplier_id, l.quantity, l.unit_price FROM purchases_order_lines l "
                             f"JOIN purchases_orders o ON o.id = l.order_id WHERE {where}", tuple(params)):
        figures = out.setdefault(line["supplier_id"], {"count": 0, "total_ht": 0.0})
        figures["total_ht"] += line_amount(line)
    for figures in out.values():
        figures["total_ht"] = cents(figures["total_ht"])
    return out
