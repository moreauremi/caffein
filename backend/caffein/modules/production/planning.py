# SPDX-License-Identifier: AGPL-3.0-or-later
"""Calculs de la Production, en Python : besoins, temps, coûts, stock disponible, manques et retards.

- besoins en composants : nomenclature active de l'article, pertes comprises (Données techniques, `components_for`) ;
- temps prévu d'une opération : réglage + temps unitaire × quantité, poste par poste (gamme active) ;
- coût matière : Σ besoin × coût de revient du composant ; coût des opérations : Σ temps prévu / 60 × coût horaire
  du poste ; coût unitaire : coût total ÷ quantité ;
- stock disponible d'un composant (Logistique) : dans l'entrepôt de l'ordre, ou dans tous les entrepôts s'il n'en
  désigne pas ; manque : besoin − stock disponible, s'il est positif.

Un ordre en brouillon est une prévision : ses besoins et ses temps suivent la nomenclature et la gamme du moment.
Au lancement, ils sont enregistrés avec l'ordre et ne bougent plus. Les coûts, eux, suivent toujours les prix.
"""

from __future__ import annotations

from ... import db
from ...utils import today
from ..stock import services as stock
from ..technical import services as technical

OPEN = ("draft", "released")  # pas encore fabriqués : le stock disponible et les manques ont un sens


def is_forecast(row: dict) -> bool:
    """Brouillon, ou fiche en cours de création : les lignes viennent de la nomenclature et de la gamme actives."""
    return row.get("status") in (None, "", "draft")


def is_late(row: dict) -> bool:
    """Ordre lancé dont la fin prévue est passée (même règle que le chiffre clé « Ordres de fabrication en retard »)."""
    end = row.get("planned_end")
    return row.get("status") == "released" and bool(end) and str(end) < today().isoformat()


def _positive(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def operations(routing: dict | None, quantity: float) -> list[dict]:
    """Opérations d'une gamme pour `quantity` unités : temps prévu = réglage + temps unitaire × quantité."""
    return [{"workcenter_id": step["workcenter_id"], "description": step["description"] or "",
             "planned_minutes": round((step["setup_minutes"] or 0) + (step["run_minutes"] or 0) * quantity, 6)}
            for step in (routing or {}).get("steps", [])]


def stored_lines(order_ids: list) -> dict[int, dict[str, list[dict]]]:
    """Composants et opérations enregistrés au lancement de plusieurs ordres, en deux requêtes (listes)."""
    ids = sorted({i for i in order_ids if i})
    out: dict[int, dict[str, list[dict]]] = {i: {"components": [], "operations": []} for i in ids}
    if not ids:
        return out
    marks = ", ".join("?" for _ in ids)
    for line in db.fetch_all(f"SELECT order_id, article_id, quantity FROM production_order_components "
                             f"WHERE order_id IN ({marks}) ORDER BY order_id, position, id", tuple(ids)):
        out[line.pop("order_id")]["components"].append(line)
    for line in db.fetch_all(f"SELECT order_id, workcenter_id, description, planned_minutes FROM production_order_operations "
                             f"WHERE order_id IN ({marks}) ORDER BY order_id, position, id", tuple(ids)):
        out[line.pop("order_id")]["operations"].append(line)
    return out


class Context:
    """Lectures partagées par un même calcul : une liste de 50 ordres ne relit pas 50 fois la même nomenclature,
    le même coût de revient ou le même stock."""

    def __init__(self) -> None:
        self.costs: dict = {}                        # coûts de revient déjà calculés (technical.cost_price)
        self._needs: dict = {}
        self._routings: dict = {}
        self._articles: dict = {}
        self._stock: dict = {}
        self._workcenters: dict | None = None

    def forecast(self, article_id: int | None, quantity: object) -> tuple[list[dict], list[dict]]:
        """Besoins et opérations prévus pour fabriquer `quantity` unités ; rien sans article ni quantité positive."""
        if not article_id or not _positive(quantity):
            return [], []
        key = (article_id, quantity)
        if key not in self._needs:
            self._needs[key] = technical.components_for(article_id, quantity)
        if article_id not in self._routings:
            self._routings[article_id] = technical.active_routing(article_id)
        components = [{"article_id": c["article_id"], "quantity": c["quantity"]} for c in self._needs[key]]
        return components, operations(self._routings[article_id], quantity)

    def article(self, article_id: int | None) -> dict | None:
        if article_id not in self._articles:
            self._articles[article_id] = technical.article(article_id)
        return self._articles[article_id]

    def stocked(self, article_id: int | None) -> bool:
        """Un service ne se stocke pas : ni stock disponible, ni manque."""
        article = self.article(article_id)
        return bool(article and article["kind"] != "service")

    def on_hand(self, article_id: int, warehouse_id: int | None) -> float:
        key = (article_id, warehouse_id or None)
        if key not in self._stock:
            self._stock[key] = stock.on_hand(article_id, warehouse_id or None)
        return self._stock[key]

    def cost(self, article_id: int | None) -> float | None:
        return technical.cost_price(article_id, self.costs)

    def workcenter(self, workcenter_id: int | None) -> dict:
        if self._workcenters is None:
            self._workcenters = {r["id"]: r for r in db.fetch_all("SELECT id, name, hourly_cost FROM technical_workcenters")}
        return self._workcenters.get(workcenter_id) or {}


def shortage(need: float, available: float) -> float:
    """Ce qui manque pour couvrir le besoin (0 si le stock suffit)."""
    return round(max((need or 0) - (available or 0), 0.0), 6)


def figures(row: dict, components: list[dict], operations: list[dict], ctx: Context) -> dict:
    """Annote les lignes (stock disponible, manque, coût d'une opération) et renvoie les champs calculés de l'ordre.
    Un ordre terminé ou annulé n'a plus ni stock disponible ni manque : ses composants sont consommés ou inutiles."""
    open_order = (row.get("status") or "draft") in OPEN
    material = labour = 0.0
    short = 0
    for line in components:
        need = line.get("quantity") or 0
        if open_order and ctx.stocked(line.get("article_id")):
            line["available"] = ctx.on_hand(line["article_id"], row.get("warehouse_id"))
            line["shortage"] = shortage(need, line["available"])
            if line["shortage"] > 0:
                short += 1
        else:
            line["available"] = line["shortage"] = None
        material += need * (ctx.cost(line.get("article_id")) or 0)
    for line in operations:
        rate = ctx.workcenter(line.get("workcenter_id")).get("hourly_cost") or 0
        line["cost"] = round((line.get("planned_minutes") or 0) / 60 * rate, 2)
        labour += line["cost"]
    material_cost = round(material, 2) if components else None
    labour_cost = round(labour, 2) if operations else None
    total = None if material_cost is None and labour_cost is None else round((material_cost or 0) + (labour_cost or 0), 2)
    quantity = row.get("quantity")
    return {
        "material_cost": material_cost, "labour_cost": labour_cost, "total_cost": total,
        "unit_cost": round(total / quantity, 2) if total is not None and _positive(quantity) else None,
        "shortages": short if open_order else None, "late": is_late(row),
    }
