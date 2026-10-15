# SPDX-License-Identifier: AGPL-3.0-or-later
"""Moteur de données générique.

Un module déclare ses entités (une table SQL, ses champs typés, ses lignes enfants, ses actions, ses
calculs) ; ce moteur en tire la liste (recherche, filtres, tri, pagination), la fiche, la création, la
modification, la suppression et les actions, avec validation complète côté serveur. L'API (entity_api.py)
et les écrans de l'interface (EntityPage) s'appuient sur la même déclaration, décrite par `meta()`.

Sécurité : les noms de tables et de colonnes viennent du code des modules et sont vérifiés à
l'enregistrement ; tout ce qui vient de l'utilisateur passe en paramètre SQL ou est comparé à la
liste des champs déclarés.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .. import db
from ..utils import parse_date, today
from .errors import Conflict, Forbidden, NotFound
from .modules import MANAGE, READ, WRITE, Label

_IDENT = re.compile(r"^[a-z][a-z0-9_]*$")
TYPES = ("text", "longtext", "email", "phone", "int", "decimal", "money", "percent", "date", "bool", "enum", "ref", "code")
TEXT_TYPES = ("text", "longtext", "email", "phone", "code")
MAX_PAGE = 200
SQLITE_INT = 2**63  # entiers SQLite : de -2^63 à 2^63 - 1


@dataclass
class Field:
    name: str
    label: Label
    type: str = "text"
    required: bool = False
    unique: bool = False
    # Liste de choix (enum, ou valeurs numériques permises) : (valeur, libellé) ou (valeur, libellé, ton)
    # ; le ton colore le badge dans les listes : good | warn | bad | info | accent | outline.
    choices: tuple[tuple, ...] = ()
    ref: str | None = None                        # « technical.articles » pour un champ de type ref
    fill: dict[str, str] | None = None            # ref : champs recopiés de la fiche choisie {champ: champ_de_la_fiche}
    default: Any = None                           # valeur, ou fonction sans argument (date du jour…)
    readonly: bool = False                        # rempli par le serveur, jamais par le formulaire
    computed: bool = False                        # pas une colonne : calculé par Entity.compute
    list: bool = False                            # colonne de la liste
    search: bool = False                          # pris en compte par la recherche
    filter: bool = False                          # proposé comme filtre de la liste
    min: float | None = None
    max: float | None = None
    maxlength: int | None = None
    sensitive: bool = False                       # visible et modifiable seulement avec le niveau « gestion »
    hidden: bool = False                          # lu avec la fiche (actions, calculs) mais jamais affiché
    help: Label | None = None
    prefix: str | None = None                     # type code : « CF » → CF-2026-0001
    yearly: bool = True                           # type code : numéro par année (CF-2026-0001) ou continu (ART-0001)
    width: str = "half"                           # mise en page du formulaire : half | full

    def __post_init__(self) -> None:
        if not _IDENT.match(self.name):
            raise ValueError(f"Nom de champ invalide : {self.name!r}")
        if self.type not in TYPES:
            raise ValueError(f"Type de champ inconnu : {self.type!r}")
        if self.type == "ref" and not self.ref:
            raise ValueError(f"Le champ {self.name} doit indiquer l'entité référencée (ref=…).")
        if self.type == "enum" and not self.choices:
            raise ValueError(f"Le champ {self.name} doit indiquer ses choix.")
        if any(not isinstance(c, tuple) or len(c) not in (2, 3) for c in self.choices):
            raise ValueError(f"Le champ {self.name} : choix (valeur, libellé) ou (valeur, libellé, ton).")
        if self.maxlength is None:
            self.maxlength = 5000 if self.type == "longtext" else 200
        for name in (self.fill or {}).values():
            if not _IDENT.match(name):
                raise ValueError(f"Champ recopié invalide : {name!r}")

    def initial(self) -> Any:
        return self.default() if callable(self.default) else self.default


@dataclass
class Child:
    """Lignes rattachées à une fiche (lignes de commande, composants…) : une table à part, triée par `position`."""
    key: str
    label: Label
    table: str
    fk: str
    fields: list[Field]
    min_rows: int = 0
    max_rows: int = 500

    def __post_init__(self) -> None:
        for name in (self.key, self.table, self.fk):
            if not _IDENT.match(name):
                raise ValueError(f"Identifiant invalide : {name!r}")


@dataclass
class Action:
    """Bouton de la fiche : `run(row, payload, user)` fait le traitement et peut renvoyer un message."""
    key: str
    label: Label
    run: Callable[[dict, dict, dict], Any]
    when: Callable[[dict], bool] = lambda row: True
    level: int = WRITE
    confirm: Label | None = None
    style: str = "default"          # default | primary | danger
    icon: str | None = None


@dataclass
class Entity:
    module: str
    name: str
    table: str
    label: Label
    plural: Label
    fields: list[Field]
    title: str                                        # champ qui désigne une fiche (références, titres)
    subtitle: str | None = None
    order_by: str = "id DESC"
    children: list[Child] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    # Ajoute les champs calculés (Python). Reçoit des fiches avec leurs lignes (fiche, aperçu de saisie)
    # ou sans (liste) : dans ce cas, calculer par une requête groupée.
    compute: Callable[[list[dict]], None] | None = None
    prepare: Callable[[dict, dict | None], None] | None = None   # ajuste les valeurs avant contrôle (signe, champ dérivé…)
    validate: Callable[[dict, dict | None], None] | None = None  # contrôles métier (ValueError)
    after_save: Callable[[int, bool], None] | None = None
    before_delete: Callable[[dict], None] | None = None          # Conflict pour interdire
    locked: Callable[[dict], str | None] | None = None           # message si la fiche n'est plus modifiable
    readonly: bool = False                                       # vue SQL : consultation seulement
    delete_level: int = MANAGE
    icon: str | None = None
    description: Label | None = None
    board: str | None = None                                      # champ à choix (statut…) : vue en colonnes
    active: str | None = None                                     # champ oui/non : seules les fiches actives sont proposées

    def __post_init__(self) -> None:
        for name in (self.module, self.name, self.table):
            if not _IDENT.match(name):
                raise ValueError(f"Identifiant invalide : {name!r}")
        names = [f.name for f in self.fields]
        if len(names) != len(set(names)):
            raise ValueError(f"Champs en double dans {self.key}")
        if self.title not in names:
            raise ValueError(f"{self.key} : le champ titre {self.title!r} n'est pas déclaré.")
        if self.active is not None and (self.field(self.active) is None or self.field(self.active).type != "bool"):
            raise ValueError(f"{self.key} : le champ « actif » doit être un champ oui/non ({self.active!r}).")
        if self.board is not None:
            board = self.field(self.board)
            if board is None or board.type != "enum" or board.computed:
                raise ValueError(f"{self.key} : la vue en colonnes suit un champ à choix enregistré ({self.board!r}).")

    @property
    def key(self) -> str:
        return f"{self.module}.{self.name}"

    def field(self, name: str) -> Field | None:
        return next((f for f in self.fields if f.name == name), None)


ENTITIES: dict[str, Entity] = {}

# Colonnes hors entités qui désignent une fiche d'une entité (ex. lignes de factures → articles) :
# (table, colonne, entité référencée, libellé). Les champs `ref` des entités sont trouvés tout seuls.
REFERENCES: list[tuple[str, str, str, Label]] = []


def register(entity: Entity) -> Entity:
    if entity.key in ENTITIES and ENTITIES[entity.key] is not entity:
        raise ValueError(f"Entité déjà enregistrée : {entity.key}")
    ENTITIES[entity.key] = entity
    return entity


def get(key: str) -> Entity:
    from . import modules

    modules.load()
    entity = ENTITIES.get(key)
    if entity is None:
        raise NotFound("Entité inconnue")
    return entity


# ═════════════════════════════════════════════════════════════════════════
# Champs actifs : une référence vers un module désactivé disparaît
# ═════════════════════════════════════════════════════════════════════════
def _ref_entity(fld: Field) -> Entity | None:
    from . import modules

    target = ENTITIES.get(fld.ref or "")
    if target is None or not modules.is_enabled(target.module):
        return None
    return target


def visible_fields(entity: Entity, fields: list[Field], level: int) -> list[Field]:
    out = []
    for fld in fields:
        if fld.sensitive and level < MANAGE:
            continue
        if fld.type == "ref" and _ref_entity(fld) is None:
            continue
        out.append(fld)
    return out


def _columns(entity: Entity) -> list[Field]:
    return [f for f in entity.fields if not f.computed]


# ═════════════════════════════════════════════════════════════════════════
# Lecture
# ═════════════════════════════════════════════════════════════════════════
def _select(entity: Entity, fields: list[Field], alias: str = "t") -> tuple[str, str]:
    """Colonnes et jointures : chaque référence est accompagnée de son libellé (<champ>__label)."""
    cols = [f"{alias}.id AS id"]
    joins = []
    for i, fld in enumerate(f for f in fields if not f.computed):
        cols.append(f"{alias}.{fld.name} AS {fld.name}")
        if fld.type == "ref":
            target = _ref_entity(fld)
            if target is not None:
                ra = f"r{i}"
                joins.append(f"LEFT JOIN {target.table} {ra} ON {ra}.id = {alias}.{fld.name}")
                cols.append(f"{ra}.{target.title} AS {fld.name}__label")
    return ", ".join(cols), " ".join(joins)


def _table_columns(table: str) -> set[str]:
    with db.connect() as conn:
        return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def _bools(rows: list[dict], fields: list[Field]) -> None:
    for row in rows:
        for fld in fields:
            if fld.type == "bool" and fld.name in row and row[fld.name] is not None:
                row[fld.name] = bool(row[fld.name])


def _coerce_filter(fld: Field, value: str) -> Any:
    if fld.type in ("int", "ref"):
        number = int(value)
        if not -SQLITE_INT <= number < SQLITE_INT:
            raise ValueError("Filtre hors limites.")
        return number
    if fld.type == "bool":
        return 1 if value in ("1", "true", "oui", "yes") else 0
    if fld.type == "enum":
        if value not in {str(c[0]) for c in fld.choices}:
            raise ValueError("Filtre invalide.")
        return next(c[0] for c in fld.choices if str(c[0]) == value)
    return value


def _where(entity: Entity, fields: list[Field], q: str | None, filters: dict[str, str] | None) -> tuple[list[str], list]:
    """Conditions de la recherche et des filtres d'une liste."""
    where, params = [], []
    if q:
        terms = []
        pattern = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        searchable = [f for f in fields if f.search and not f.computed] or [entity.field(entity.title)]
        for fld in searchable:
            terms.append(f"t.{fld.name} LIKE ? ESCAPE '\\'")
            params.append(pattern)
        where.append("(" + " OR ".join(terms) + ")")
    for name, value in (filters or {}).items():
        fld = entity.field(name)
        if fld is None or fld not in fields or not fld.filter or fld.computed or value in ("", None):
            continue
        try:
            where.append(f"t.{fld.name} = ?")
            params.append(_coerce_filter(fld, value))
        except ValueError as exc:
            raise ValueError(f"Filtre « {name} » invalide.") from exc
    return where, params


def _order(entity: Entity, fields: list[Field], sort: str | None, direction: str) -> str:
    order = entity.order_by.replace("t.", "")
    order = ", ".join(f"t.{part.strip()}" for part in order.split(","))
    if sort:
        fld = entity.field(sort)
        if sort == "id" or (fld is not None and fld in fields and not fld.computed):
            order = f"t.{sort} {'DESC' if direction == 'desc' else 'ASC'}, t.id DESC"
    return order


def _sql_where(where: list[str]) -> str:
    return f"WHERE {' AND '.join(where)}" if where else ""


def _rows(entity: Entity, fields: list[Field], where: list[str], params: list, order: str, size: int, offset: int) -> list[dict]:
    """Une page de fiches, avec les libellés des références et les champs calculés."""
    cols, joins = _select(entity, fields)
    rows = db.fetch_all(f"SELECT {cols} FROM {entity.table} t {joins} {_sql_where(where)} ORDER BY {order} LIMIT ? OFFSET ?",
                        (*params, size, offset))
    _bools(rows, fields)
    if entity.compute and rows:
        entity.compute(rows)
    _strip_hidden(rows, entity, fields)
    return rows


def list_rows(entity: Entity, level: int, *, q: str | None = None, filters: dict[str, str] | None = None,
              sort: str | None = None, direction: str = "asc", page: int = 1, size: int = 50) -> dict:
    fields = visible_fields(entity, entity.fields, level)
    where, params = _where(entity, fields, q, filters)
    order = _order(entity, fields, sort, direction)
    size = max(1, min(int(size or 50), MAX_PAGE))
    page = max(1, int(page or 1))
    total = db.fetch_one(f"SELECT COUNT(*) AS n FROM {entity.table} t {_sql_where(where)}", tuple(params))["n"]
    rows = _rows(entity, fields, where, params, order, size, (page - 1) * size)
    return {"rows": rows, "total": total, "page": page, "size": size}


BOARD_SUM_LIMIT = 5000  # au-delà, pas de total pour un montant calculé (il faudrait calculer chaque fiche)


def board(entity: Entity, level: int, *, q: str | None = None, filters: dict[str, str] | None = None,
          sort: str | None = None, direction: str = "asc", size: int = 30) -> dict:
    """Vue en colonnes, une par valeur du champ `Entity.board` (statut, étape…), avec la recherche et les filtres
    de la liste. Le nombre de fiches et le total de chaque colonne (premier montant affiché dans la liste)
    sont calculés par le serveur ; chaque colonne porte ses `size` premières fiches."""
    if not entity.board:
        raise NotFound("Cette liste n'a pas de vue en colonnes.")
    fields = visible_fields(entity, entity.fields, level)
    column = entity.field(entity.board)
    if column not in fields:
        raise NotFound("Cette liste n'a pas de vue en colonnes.")
    where, params = _where(entity, fields, q, {k: v for k, v in (filters or {}).items() if k != column.name})
    order = _order(entity, fields, sort, direction)
    size = max(1, min(int(size or 30), MAX_PAGE))
    amount = next((f for f in fields if f.type == "money" and f.list and not f.hidden), None)
    stored = f", SUM(t.{amount.name}) AS amount" if amount and not amount.computed else ""
    stats = {r["value"]: dict(r) for r in db.fetch_all(
        f"SELECT t.{column.name} AS value, COUNT(*) AS n{stored} FROM {entity.table} t {_sql_where(where)} "
        f"GROUP BY t.{column.name}", tuple(params))}
    if amount and amount.computed:  # montant calculé en Python (total des lignes…) : sur toutes les fiches de la vue
        if sum(stat["n"] for stat in stats.values()) <= BOARD_SUM_LIMIT:
            for row in _rows(entity, fields, where, params, order, BOARD_SUM_LIMIT, 0):
                stat = stats.get(row.get(column.name))
                if stat is not None:
                    stat["amount"] = (stat.get("amount") or 0) + (row.get(amount.name) or 0)
        else:
            amount = None
    columns = []
    for choice in column.choices:
        stat = stats.get(choice[0]) or {}
        count = stat.get("n", 0)
        rows = _rows(entity, fields, [*where, f"t.{column.name} = ?"], [*params, choice[0]], order, size, 0) if count else []
        columns.append({"value": choice[0], "label": choice[1], "tone": choice[2] if len(choice) > 2 else None,
                        "count": count, "amount": round(stat.get("amount") or 0, 2) if amount else None, "rows": rows})
    return {"field": column.name, "amount_field": amount.name if amount else None,
            "amount_label": amount.label if amount else None, "columns": columns}


def _csv_value(fld: Field, row: dict, language: str) -> str:
    """Valeur d'une cellule d'export, mise en forme par le serveur (nombres et dates lisibles par un tableur)."""
    value = row.get(fld.name)
    if value is None or value == "":
        return ""
    fr = language != "en"
    if fld.type in ("int", "decimal", "money", "percent"):
        text = f"{value:.2f}" if fld.type == "money" else f"{value:g}" if isinstance(value, float) else str(value)
        return text.replace(".", ",") if fr else text
    if fld.type == "date":
        d = parse_date(value)
        return d.strftime("%d/%m/%Y") if d and fr else str(value)
    if fld.type == "bool":
        return ("Oui" if value else "Non") if fr else ("Yes" if value else "No")
    if fld.type == "enum":
        choice = next((c for c in fld.choices if str(c[0]) == str(value)), None)
        return choice[1][0 if fr else 1] if choice else str(value)
    if fld.type == "ref":
        return str(row.get(f"{fld.name}__label") or f"#{value}")
    return str(value)


def export_rows(entity: Entity, level: int, *, language: str = "fr", limit: int = 10_000, **query) -> tuple[list[str], list[list[str]]]:
    """Liste filtrée (mêmes recherche, filtres et tri que l'écran) → en-têtes et cellules d'un export tableur."""
    fields = [f for f in visible_fields(entity, entity.fields, level) if not f.hidden]
    headers = [f.label[0 if language != "en" else 1] for f in fields]
    out: list[list[str]] = []
    page = 1
    while len(out) < limit:
        result = list_rows(entity, level, page=page, size=MAX_PAGE, **query)
        out += [[_csv_value(f, row, language) for f in fields] for row in result["rows"]]
        if page * MAX_PAGE >= result["total"]:
            break
        page += 1
    return headers, out[:limit]


def _strip_hidden(rows: list[dict], entity: Entity, fields: list[Field]) -> None:
    hidden = {f.name for f in entity.fields} - {f.name for f in fields}
    for row in rows:
        for name in hidden:
            row.pop(name, None)
            row.pop(f"{name}__label", None)


def _fetch(entity: Entity, row_id: int, fields: list[Field] | None = None) -> dict:
    fields = fields if fields is not None else visible_fields(entity, entity.fields, MANAGE)
    cols, joins = _select(entity, fields)
    row = db.fetch_one(f"SELECT {cols} FROM {entity.table} t {joins} WHERE t.id = ?", (row_id,))
    if row is None:
        raise NotFound(f"{entity.label[0]} introuvable")
    _bools([row], fields)
    return row


def _children(entity: Entity, row_id: int, level: int) -> dict[str, list[dict]]:
    out = {}
    for child in entity.children:
        fields = visible_fields(entity, child.fields, level)
        cols, joins = _select(entity, fields, alias="t")
        rows = db.fetch_all(f"SELECT {cols} FROM {child.table} t {joins} WHERE t.{child.fk} = ? ORDER BY t.position, t.id",
                            (row_id,))
        _bools(rows, fields)
        out[child.key] = rows
    return out


def get_row(entity: Entity, row_id: int, level: int, user: dict | None = None) -> dict:
    fields = visible_fields(entity, entity.fields, level)
    row = _fetch(entity, row_id, fields)
    row.update(_children(entity, row_id, level))
    if entity.compute:
        entity.compute([row])
    _strip_hidden([row], entity, fields)
    row["_locked"] = entity.locked(row) if entity.locked else None
    row["_actions"] = [a.key for a in entity.actions if level >= a.level and _when(a, row)]
    row["_deletable"] = not entity.readonly and level >= entity.delete_level and _delete_refusal(entity, row) is None
    return row


def _delete_refusal(entity: Entity, row: dict) -> str | None:
    """Pourquoi la fiche ne se supprime pas, ou None. La règle du module (`before_delete`) décide seule quand elle
    existe : une commande annulée, verrouillée, se supprime si le module le permet. Sans règle, une fiche
    verrouillée ne se supprime pas."""
    if entity.before_delete:
        try:
            entity.before_delete(row)
        except (Conflict, ValueError) as exc:
            return str(exc)
        return None
    return entity.locked(row) if entity.locked else None


def _when(action: Action, row: dict) -> bool:
    try:
        return bool(action.when(row))
    except (KeyError, TypeError):
        return False


# ═════════════════════════════════════════════════════════════════════════
# Écriture
# ═════════════════════════════════════════════════════════════════════════
def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _clean_value(fld: Field, value: Any, label: str) -> Any:
    """Valeur reçue → valeur à enregistrer, ou ValueError avec un message pour l'utilisateur.
    Convention des tables : les textes sont `NOT NULL DEFAULT ''` (vide = ''), le reste accepte NULL."""
    t = fld.type
    if _empty(value):
        return "" if t in TEXT_TYPES else None
    if t in TEXT_TYPES:
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise ValueError(f"{label} : valeur invalide.")
        text = str(value).strip() if t != "longtext" else str(value).strip("\n ")
        if len(text) > (fld.maxlength or 200):
            raise ValueError(f"{label} : {fld.maxlength} caractères au plus.")
        if t == "email" and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", text):
            raise ValueError(f"{label} : adresse email invalide.")
        if t == "phone" and not re.fullmatch(r"[0-9+(). \-]{4,30}", text):
            raise ValueError(f"{label} : numéro invalide.")
        return text
    if t in ("int", "ref"):
        if isinstance(value, bool):
            raise ValueError(f"{label} : valeur invalide.")
        try:
            number = int(value) if not isinstance(value, float) or value.is_integer() else None
        except (TypeError, ValueError, OverflowError):
            number = None
        if number is None:
            raise ValueError(f"{label} : nombre entier attendu.")
        if not -SQLITE_INT <= number < SQLITE_INT:
            raise ValueError(f"{label} : nombre hors limites.")
        if t == "int":
            _bounds(fld, number, label)
        return number
    if t in ("decimal", "money", "percent"):
        if isinstance(value, bool):
            raise ValueError(f"{label} : valeur invalide.")
        try:
            number = float(str(value).replace(",", ".").replace(" ", "").replace(" ", ""))
        except (TypeError, ValueError):
            raise ValueError(f"{label} : nombre attendu.") from None
        if number != number or number in (float("inf"), float("-inf")):
            raise ValueError(f"{label} : nombre attendu.")
        _bounds(fld, number, label)
        if fld.choices and number not in {float(c[0]) for c in fld.choices}:
            raise ValueError(f"{label} : valeur non proposée.")
        return round(number, 2) if t == "money" else round(number, 6)
    if t == "date":
        d = parse_date(value) if isinstance(value, (str, date)) else None
        if d is None:
            raise ValueError(f"{label} : date invalide.")
        return d.isoformat()
    if t == "bool":
        if isinstance(value, bool):
            return int(value)
        if value in (0, 1, "0", "1", "true", "false"):
            return int(value in (1, "1", "true"))
        raise ValueError(f"{label} : oui ou non attendu.")
    if t == "enum":
        allowed = {str(c[0]): c[0] for c in fld.choices}
        if str(value) not in allowed:
            raise ValueError(f"{label} : valeur non proposée.")
        return allowed[str(value)]
    raise ValueError(f"{label} : type non géré.")


def _bounds(fld: Field, number: float, label: str) -> None:
    if fld.min is not None and number < fld.min:
        raise ValueError(f"{label} : {fld.min:g} au minimum.")
    if fld.max is not None and number > fld.max:
        raise ValueError(f"{label} : {fld.max:g} au maximum.")


def _check_ref(fld: Field, value: Any, label: str) -> None:
    if value is None:
        return
    target = _ref_entity(fld)
    if target is None or not db.fetch_one(f"SELECT 1 FROM {target.table} WHERE id = ?", (value,)):
        raise ValueError(f"{label} : fiche introuvable.")


def _clean_record(entity: Entity, fields: list[Field], data: dict, existing: dict | None) -> dict:
    values = {}
    for fld in fields:
        if fld.readonly or fld.computed:
            continue
        label = fld.label[0]
        if fld.name in data:
            value = _clean_value(fld, data[fld.name], label)
            if value is None and fld.type == "bool":  # ni oui ni non : la valeur enregistrée, ou la valeur par défaut
                if existing is not None:
                    continue
                value = int(bool(fld.initial()))
        elif existing is None:
            value = fld.initial()
        else:
            continue
        if fld.type == "ref":
            _check_ref(fld, value, label)
        values[fld.name] = value
    _fill_from_refs(fields, values, data)
    for fld in fields:
        if fld.name in values and _empty(values[fld.name]) and fld.required and not (fld.type == "code" and fld.prefix):
            raise ValueError(f"{fld.label[0]} : obligatoire.")
    return values


def safe_fill(target: Entity, fill: dict[str, str] | None) -> dict[str, str]:
    """Champs recopiables d'une fiche : jamais un champ sensible (salaire…), jamais un champ calculé."""
    out = {}
    for local, remote in (fill or {}).items():
        fld = target.field(remote)
        if remote == "id" or (fld is not None and not fld.sensitive and not fld.computed):
            out[local] = remote
    return out


def _fill_from_refs(fields: list[Field], values: dict, data: dict) -> None:
    """Recopie les champs déclarés dans `fill` depuis la fiche référencée, s'ils sont restés vides
    (ex. article choisi sur une ligne → description et prix de l'article)."""
    for fld in fields:
        if fld.type != "ref" or not fld.fill or values.get(fld.name) is None:
            continue
        target = _ref_entity(fld)
        if target is None:
            continue
        fill = safe_fill(target, fld.fill)
        if not fill:
            continue
        source = db.fetch_one(f"SELECT {', '.join(dict.fromkeys(fill.values()))} FROM {target.table} WHERE id = ?",
                              (values[fld.name],))
        for local, remote in fill.items():
            local_field = next((f for f in fields if f.name == local), None)
            if source is None or local_field is None or local_field.readonly or local_field.computed:
                continue
            if local not in data or _empty(data.get(local)):
                values[local] = source[remote] if source[remote] is not None else values.get(local)


def _check_unique(entity: Entity, values: dict, row_id: int | None) -> None:
    for fld in entity.fields:
        if fld.unique and not _empty(values.get(fld.name)):
            other = db.fetch_one(f"SELECT id FROM {entity.table} WHERE {fld.name} = ? COLLATE NOCASE AND id != ?",
                                 (values[fld.name], row_id or 0))
            if other:
                raise ValueError(f"{fld.label[0]} : « {values[fld.name]} » existe déjà.")


def next_code(table: str, column: str, prefix: str, ref: date | None = None, yearly: bool = True,
              conn: sqlite3.Connection | None = None) -> str:
    """Numéro suivant : PREFIX-2026-0001 (ou PREFIX-0001 sans l'année). Avec `conn` (transaction ouverte par
    BEGIN IMMEDIATE), le numéro est lu sous verrou d'écriture : deux créations simultanées n'ont jamais le même."""
    stem = f"{prefix}-{(ref or today()).year}-" if yearly else f"{prefix}-"
    # longueur d'abord : après PREFIX-9999 vient PREFIX-10000, plus long mais « plus petit » dans l'ordre alphabétique
    sql = (f"SELECT {column} AS code FROM {table} WHERE {column} LIKE ? ESCAPE '\\' "
           f"ORDER BY LENGTH({column}) DESC, {column} DESC LIMIT 1")
    pattern = (stem.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",)
    row = conn.execute(sql, pattern).fetchone() if conn is not None else db.fetch_one(sql, pattern)
    seq = 1
    if row and row["code"]:
        tail = row["code"][len(stem):]
        seq = int(tail) + 1 if tail.isdigit() else 1
    return f"{stem}{seq:04d}"


def writable(child: Child) -> bool:
    """Des lignes dont tous les champs sont remplis par le serveur (besoins calculés…) ne se saisissent pas."""
    return any(not f.readonly and not f.computed for f in child.fields)


LINE_ID = "__id"  # identifiant d'une ligne existante, gardé pendant l'enregistrement (pas une colonne)


def _clean_children(entity: Entity, data: dict, level: int, existing: dict | None = None) -> dict[str, list[dict]]:
    """Lignes reçues → lignes à enregistrer. Une ligne qui porte l'`id` d'une ligne de la fiche la met à jour : ses
    colonnes absentes ou invisibles pour l'utilisateur (référence vers un module désactivé, champ sensible) sont
    conservées. Les autres lignes sont nouvelles ; les lignes enregistrées absentes de la liste sont supprimées."""
    out = {}
    for child in entity.children:
        if child.key not in data or not writable(child):
            continue
        raw_rows = data[child.key]
        if not isinstance(raw_rows, list):
            raise ValueError(f"{child.label[0]} : liste attendue.")
        if len(raw_rows) > child.max_rows:
            raise ValueError(f"{child.label[0]} : {child.max_rows} lignes au plus.")
        fields = visible_fields(entity, child.fields, level)
        stored = {line["id"]: line for line in (existing or {}).get(child.key) or []}
        columns = [f.name for f in child.fields if not f.computed]
        rows, seen = [], set()
        for i, raw in enumerate(raw_rows, start=1):
            if not isinstance(raw, dict):
                raise ValueError(f"{child.label[0]}, ligne {i} : invalide.")
            line_id = raw.get("id")
            valid_id = isinstance(line_id, int) and not isinstance(line_id, bool) and line_id not in seen
            known = stored.get(line_id) if valid_id else None
            try:
                values = _clean_record(entity, fields, raw, known)
            except ValueError as exc:
                raise ValueError(f"{child.label[0]}, ligne {i} — {exc}") from None
            if known is not None:  # ligne complète pour les contrôles du module
                seen.add(line_id)
                values = {**{c: known[c] for c in columns if c in known}, **values, LINE_ID: line_id}
            rows.append(values)
        if len(rows) < child.min_rows:
            raise ValueError(f"{child.label[0]} : au moins {child.min_rows} ligne(s).")
        out[child.key] = rows
    return out


def _write_children(conn: sqlite3.Connection, entity: Entity, row_id: int, children: dict[str, list[dict]]) -> None:
    for child in entity.children:
        if child.key not in children:
            continue
        stored = {r["id"] for r in conn.execute(f"SELECT id FROM {child.table} WHERE {child.fk} = ?", (row_id,))}
        kept = set()
        for position, line in enumerate(children[child.key]):
            values = {k: v for k, v in line.items() if k != LINE_ID}
            line_id = line.get(LINE_ID)
            if line_id in stored:  # mise à jour : seules les colonnes reçues changent
                sets = {**values, "position": position}
                conn.execute(f"UPDATE {child.table} SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?",
                             (*sets.values(), line_id))
                kept.add(line_id)
                continue
            values = {k: v for k, v in values.items() if v is not None}
            cols = [child.fk, "position", *values]
            conn.execute(f"INSERT INTO {child.table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                         (row_id, position, *values.values()))
        gone = sorted(stored - kept)
        if gone:
            conn.execute(f"DELETE FROM {child.table} WHERE id IN ({', '.join('?' for _ in gone)})", tuple(gone))


def save_row(entity: Entity, data: dict, level: int, row_id: int | None = None) -> int:
    """Crée (row_id=None) ou modifie une fiche avec ses lignes, dans une seule transaction."""
    if entity.readonly:
        raise Conflict("Ces données sont calculées : elles ne se modifient pas.")
    if not isinstance(data, dict):
        raise ValueError("Données invalides.")
    existing = None
    if row_id is not None:
        existing = get_row(entity, row_id, MANAGE)
        if entity.locked and (reason := entity.locked(existing)):
            raise Conflict(reason)
    fields = visible_fields(entity, entity.fields, level)
    values = _clean_record(entity, fields, data, existing)
    children = _clean_children(entity, data, level, existing)
    auto: list[Field] = []  # numéros attribués ici : relus sous verrou au moment d'écrire
    for fld in entity.fields:
        if fld.type == "code" and fld.prefix:
            if existing is None and _empty(values.get(fld.name)):
                values[fld.name] = next_code(entity.table, fld.name, fld.prefix, yearly=fld.yearly)
                auto.append(fld)
            elif existing is not None and _empty(values.get(fld.name, "x")):
                values.pop(fld.name, None)  # un numéro attribué ne s'efface pas
    if entity.prepare:
        entity.prepare(values, existing)
    _check_unique(entity, values, row_id)
    if entity.validate:
        entity.validate({**(existing or {}), **values, **children}, existing)
    columns = _table_columns(entity.table)
    now = db.now_iso()
    if "updated_at" in columns:
        values["updated_at"] = now
    try:
        with db.connect() as conn:
            if existing is None:
                if auto:
                    conn.execute("BEGIN IMMEDIATE")
                    for fld in auto:
                        values[fld.name] = next_code(entity.table, fld.name, fld.prefix, yearly=fld.yearly, conn=conn)
                if "created_at" in columns:
                    values["created_at"] = now
                values = {k: v for k, v in values.items() if v is not None}  # les valeurs par défaut SQL s'appliquent
                cols = list(values)
                cur = conn.execute(f"INSERT INTO {entity.table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                                   tuple(values.values()))
                row_id = cur.lastrowid
            elif values:
                sets = ", ".join(f"{k} = ?" for k in values)
                conn.execute(f"UPDATE {entity.table} SET {sets} WHERE id = ?", (*values.values(), row_id))
            _write_children(conn, entity, row_id, children)
    except sqlite3.IntegrityError as exc:
        raise Conflict("Enregistrement impossible : une valeur est déjà utilisée ou une fiche liée n'existe plus.") from exc
    if entity.after_save:
        entity.after_save(row_id, existing is None)
    return row_id


def usages(entity: Entity, row_id: int) -> list[tuple[Label, int]]:
    """Où une fiche est utilisée, dans tous les modules (actifs ou non : leurs données restent en base)."""
    holders: list[tuple[str, str, Label]] = []
    for other in ENTITIES.values():
        if other.readonly:
            continue
        holders += [(other.table, f.name, other.plural) for f in other.fields if f.type == "ref" and f.ref == entity.key]
        for child in other.children:
            holders += [(child.table, f.name, other.plural) for f in child.fields if f.type == "ref" and f.ref == entity.key]
    holders += [(table, column, label) for table, column, key, label in REFERENCES if key == entity.key]
    found: dict[Label, int] = {}
    for table, column, label in holders:
        n = db.fetch_one(f"SELECT COUNT(*) AS n FROM {table} WHERE {column} = ?", (row_id,))["n"]
        if n:
            found[label] = found.get(label, 0) + n
    return list(found.items())


def delete_row(entity: Entity, row_id: int) -> None:
    if entity.readonly:
        raise Conflict("Ces données sont calculées : elles ne se suppriment pas.")
    row = get_row(entity, row_id, MANAGE)
    if entity.before_delete:
        entity.before_delete(row)
    elif entity.locked and (reason := entity.locked(row)):
        raise Conflict(reason)
    used = usages(entity, row_id)
    if used:
        detail = ", ".join(f"{label[0].lower()} : {n}" for label, n in used)
        raise Conflict(f"Suppression impossible : cette fiche est utilisée ailleurs ({detail}).")
    try:
        with db.connect() as conn:
            for child in entity.children:
                conn.execute(f"DELETE FROM {child.table} WHERE {child.fk} = ?", (row_id,))
            conn.execute(f"DELETE FROM {entity.table} WHERE id = ?", (row_id,))
    except sqlite3.IntegrityError as exc:
        raise Conflict(f"{entity.label[0]} utilisé(e) ailleurs : suppression impossible.") from exc


def preview(entity: Entity, data: dict, level: int, row_id: int | None = None) -> dict:
    """Champs calculés d'une fiche en cours de saisie, sans rien enregistrer : l'interface affiche
    les totaux calculés par le serveur. Les valeurs invalides sont ignorées (l'enregistrement les signalera)."""
    if not isinstance(data, dict):
        raise ValueError("Données invalides.")
    existing = get_row(entity, row_id, level) if row_id is not None else {}
    row: dict = {**existing, "id": row_id}
    for fld in visible_fields(entity, entity.fields, level):
        if fld.name in data and not fld.computed:
            try:
                row[fld.name] = _clean_value(fld, data[fld.name], fld.label[0])
            except ValueError:
                row[fld.name] = None
    for child in entity.children:
        if child.key not in data or not isinstance(data[child.key], list):
            continue
        fields = visible_fields(entity, child.fields, level)
        lines = []
        for raw in data[child.key][: child.max_rows]:
            line = {}
            for fld in fields:
                if fld.computed or not isinstance(raw, dict) or fld.name not in raw:
                    continue
                try:
                    line[fld.name] = _clean_value(fld, raw[fld.name], fld.label[0])
                except ValueError:
                    line[fld.name] = None
            lines.append(line)
        row[child.key] = lines
    if entity.compute:
        entity.compute([row])
    computed = {f.name: row.get(f.name) for f in entity.fields if f.computed}
    children = {c.key: [{f.name: line.get(f.name) for f in c.fields if f.computed} for line in row.get(c.key, [])]
                for c in entity.children if c.key in data}
    return {"computed": computed, "children": children}


def ref_label(key: str, row_id: int | None) -> str | None:
    """Libellé d'une fiche d'une autre entité (champ titre), ou None si le module est inactif ou la fiche absente."""
    from . import modules

    target = ENTITIES.get(key)
    if row_id is None or target is None or not modules.is_enabled(target.module):
        return None
    row = db.fetch_one(f"SELECT {target.title} AS label FROM {target.table} WHERE id = ?", (row_id,))
    return row["label"] if row else None


def run_action(entity: Entity, row_id: int, key: str, payload: dict, user: dict, level: int) -> Any:
    action = next((a for a in entity.actions if a.key == key), None)
    if action is None:
        raise NotFound("Action inconnue")
    if level < action.level:
        raise Forbidden("Droits insuffisants pour cette action.")
    row = get_row(entity, row_id, MANAGE)
    if not _when(action, row):
        raise Conflict("Cette action n'est pas possible dans l'état actuel de la fiche.")
    # `module_level` : le niveau de l'utilisateur sur le module, pour une règle plus fine que Action.level
    return action.run(row, payload if isinstance(payload, dict) else {}, {**(user or {}), "module_level": level})


def options(entity: Entity, q: str | None = None, limit: int = 20, fill: dict[str, str] | None = None) -> list[dict]:
    """Choix d'une référence : id, libellé (champ titre), complément (sous-titre) et, pour un champ qui
    recopie des valeurs (`fill`), ces valeurs prêtes à être reprises par le formulaire. Une entité qui déclare
    `active` ne propose que ses fiches actives (un fournisseur ou un salarié parti ne se choisit plus)."""
    params: list[Any] = []
    conditions = [f"{entity.active} = 1"] if entity.active else []
    title, subtitle = entity.title, entity.subtitle
    if q:
        pattern = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        cols = [title] + ([subtitle] if subtitle else []) + [f.name for f in entity.fields if f.search and not f.computed]
        conditions.append("(" + " OR ".join(f"{c} LIKE ? ESCAPE '\\'" for c in dict.fromkeys(cols)) + ")")
        params = [pattern] * len(dict.fromkeys(cols))
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sub = f", {subtitle} AS sublabel" if subtitle else ""
    fill = safe_fill(entity, fill)
    remote = list(dict.fromkeys(fill.values()))
    extra = "".join(f", {name} AS fill__{name}" for name in remote)
    rows = db.fetch_all(f"SELECT id, {title} AS label{sub}{extra} FROM {entity.table} {where} ORDER BY {title} COLLATE NOCASE "
                        f"LIMIT ?", (*params, max(1, min(limit, 50))))
    if fill:
        for row in rows:
            values = {name: row.pop(f"fill__{name}") for name in remote}
            row["fill"] = {local: values[name] for local, name in fill.items()}
    return rows


# ═════════════════════════════════════════════════════════════════════════
# Description pour l'interface
# ═════════════════════════════════════════════════════════════════════════
def _field_meta(fld: Field) -> dict:
    meta = {"name": fld.name, "label": fld.label, "type": fld.type, "required": fld.required,
            "readonly": fld.readonly or fld.computed, "computed": fld.computed, "list": fld.list, "search": fld.search,
            "filter": fld.filter, "sortable": not fld.computed, "width": fld.width}
    if fld.choices:
        meta["choices"] = [{"value": c[0], "label": c[1], **({"tone": c[2]} if len(c) > 2 else {})} for c in fld.choices]
    if fld.ref:
        meta["ref"] = fld.ref
    if fld.fill:
        meta["fill"] = list(fld.fill)
    for key in ("min", "max", "help", "prefix"):
        if getattr(fld, key) is not None:
            meta[key] = getattr(fld, key)
    if fld.type in ("text", "longtext"):
        meta["maxlength"] = fld.maxlength
    initial = fld.initial()
    if initial is not None:
        meta["default"] = initial.isoformat() if isinstance(initial, date) else initial
    return meta


def meta(entity: Entity, level: int) -> dict:
    fields = [f for f in visible_fields(entity, entity.fields, level) if not f.hidden]
    return {
        "key": entity.key, "module": entity.module, "name": entity.name, "label": entity.label, "plural": entity.plural,
        "title": entity.title, "subtitle": entity.subtitle, "icon": entity.icon, "description": entity.description,
        "readonly": entity.readonly, "board": entity.board, "fields": [_field_meta(f) for f in fields],
        "children": [{"key": c.key, "label": c.label, "min_rows": c.min_rows, "writable": writable(c),
                      "fields": [_field_meta(f) for f in visible_fields(entity, c.fields, level) if not f.hidden]}
                     for c in entity.children],
        "actions": [{"key": a.key, "label": a.label, "level": a.level, "confirm": a.confirm, "style": a.style,
                     "icon": a.icon} for a in entity.actions],
        "can_create": not entity.readonly and level >= WRITE,
        "can_edit": not entity.readonly and level >= WRITE,
        "can_delete": not entity.readonly and level >= entity.delete_level,
    }


__all__ = ["Field", "Child", "Action", "Entity", "ENTITIES", "register", "get", "list_rows", "board", "get_row", "save_row",
           "delete_row", "run_action", "options", "meta", "next_code", "visible_fields", "preview", "ref_label", "usages",
           "export_rows",
           "REFERENCES",
           "READ", "WRITE", "MANAGE"]
