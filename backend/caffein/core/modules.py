# SPDX-License-Identifier: AGPL-3.0-or-later
"""Registre des modules.

Un module déclare tout ce qui lui appartient (tables, entités, pages, routes, scripts, indicateurs,
données de démonstration) dans un objet `Module`. Le registre les charge, vérifie leurs dépendances
et sait lesquels sont actifs. Voir docs/modules.md.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .. import db
from .errors import Conflict, NotFound

Label = tuple[str, str]  # (français, anglais)

NONE, READ, WRITE, MANAGE = 0, 1, 2, 3
LEVEL_NAMES = {NONE: "none", READ: "read", WRITE: "write", MANAGE: "manage"}


@dataclass
class Page:
    """Une entrée de navigation du module : un écran généré (entité) ou un composant React du registre."""
    slug: str
    label: Label
    entity: str | None = None       # « technical.articles » : écran de liste et de fiche généré
    component: str | None = None    # « sales.invoices » : composant du registre de l'interface
    path: str | None = None         # chemin absolu (ex. « / » pour l'accueil), sinon /<module>/<page>
    admin_only: bool = False
    min_level: int = READ
    icon: str | None = None


@dataclass
class Kpi:
    """Chiffre clé d'un module, affiché sur l'accueil (et proposé dans « Mes vues »).
    `compute()` renvoie {"value": …, "count": …} ; le serveur calcule, l'interface affiche."""
    key: str                                  # « below_min » → « stock.below_min »
    label: Label
    compute: Callable[[], dict]
    unit: str = "count"                       # count | money | minutes | percent | days
    foot: Label | None = None                 # « {n} facture(s) » : {n} = count
    icon: str | None = None
    path: str | None = None                   # page ouverte au clic
    alert: Callable[[dict], bool] | None = None   # carte mise en avant (retard, rupture…)


@dataclass
class Shortcut:
    """Raccourci de l'accueil (« Nouvelle facture »…), proposé si l'utilisateur a le niveau requis."""
    key: str
    label: Label
    path: str
    icon: str | None = None
    level: int = 2                            # écriture


@dataclass
class Module:
    key: str
    slug: str
    label: Label
    description: Label
    icon: str
    order: int
    core: bool = False                       # toujours actif (Accueil, Paramètres)
    depends: tuple[str, ...] = ()
    default_enabled: bool = True             # sur une nouvelle installation
    upgrade_enabled: bool = False            # actif sur une instance d'avant les modules (fonctions existantes)
    migrations: list[tuple[int, str]] = field(default_factory=list)
    entities: list[Any] = field(default_factory=list)
    pages: list[Page] = field(default_factory=list)
    router: Any = None                       # APIRouter des routes propres au module
    jobs: tuple[str, ...] = ()               # scripts planifiés (noms dans jobs.JOBS)
    kpis: list[Kpi] = field(default_factory=list)
    shortcuts: list[Shortcut] = field(default_factory=list)
    events: dict[str, Callable[[dict], Any]] = field(default_factory=dict)  # abonnements aux événements des autres modules
    seed_demo: Callable[[], None] | None = None
    reset_tables: tuple[str, ...] = ()       # tables vidées par la réinitialisation (ordre des clés étrangères)


REGISTRY: dict[str, Module] = {}
_loaded = False


def register(module: Module) -> Module:
    if module.key in REGISTRY:
        raise ValueError(f"Module déjà enregistré : {module.key}")
    if any(m.slug == module.slug for m in REGISTRY.values()):
        raise ValueError(f"Adresse de module déjà utilisée : {module.slug}")
    REGISTRY[module.key] = module
    return module


def load() -> dict[str, Module]:
    """Charge les modules déclarés dans caffein.modules (une seule fois) et vérifie leurs dépendances."""
    global _loaded
    if not _loaded:
        from .. import modules as package

        for module in package.MODULES:
            register(module)
        for module in REGISTRY.values():
            missing = [d for d in module.depends if d not in REGISTRY]
            if missing:
                raise ValueError(f"Le module {module.key} dépend de modules inconnus : {', '.join(missing)}")
        _loaded = True
        from . import entities  # les entités des modules rejoignent le registre des entités

        for module in REGISTRY.values():
            for entity in module.entities:
                entities.register(entity)
    return REGISTRY


def ordered() -> list[Module]:
    return sorted(load().values(), key=lambda m: (m.order, m.key))


def dependency_order() -> list[Module]:
    """Modules triés pour que chacun vienne après ceux dont il dépend (migrations, données de démo)."""
    done: list[Module] = []
    seen: set[str] = set()

    def visit(module: Module, stack: tuple[str, ...] = ()) -> None:
        if module.key in seen:
            return
        if module.key in stack:
            raise ValueError(f"Dépendance circulaire : {' → '.join((*stack, module.key))}")
        for dep in module.depends:
            visit(REGISTRY[dep], (*stack, module.key))
        seen.add(module.key)
        done.append(module)

    for module in ordered():
        visit(module)
    return done


def get(key: str) -> Module:
    module = load().get(key)
    if module is None:
        raise NotFound("Module inconnu")
    return module


def by_slug(slug: str) -> Module | None:
    return next((m for m in load().values() if m.slug == slug), None)


# ── Activation ───────────────────────────────────────────────────────────
def enabled_keys() -> set[str]:
    load()
    rows = db.fetch_all("SELECT key, enabled FROM modules")
    enabled = {r["key"] for r in rows if r["enabled"]}
    return {k for k, m in REGISTRY.items() if m.core or k in enabled}


def is_enabled(key: str) -> bool:
    module = load().get(key)
    if module is None:
        return False
    if module.core:
        return True
    row = db.fetch_one("SELECT enabled FROM modules WHERE key = ?", (key,))
    return bool(row and row["enabled"])


def sync_rows(fresh_instance: bool) -> None:
    """Chaque module a sa ligne dans `modules`. Sur une instance neuve, un module suit son `default_enabled`.
    Sur une instance déjà utilisée, un nouveau module arrive désactivé, sauf au passage aux modules
    (table vide) pour ceux qui reprennent des fonctions existantes (`upgrade_enabled`)."""
    known = {r["key"] for r in db.fetch_all("SELECT key FROM modules")}
    first_sync = not known
    for module in load().values():
        if module.key not in known:
            enabled = module.core or (module.default_enabled if fresh_instance else (first_sync and module.upgrade_enabled))
            db.execute("INSERT INTO modules (key, enabled, updated_at) VALUES (?, ?, ?)",
                       (module.key, int(enabled), db.now_iso()))


def set_enabled(key: str, enabled: bool) -> None:
    module = get(key)
    if module.core:
        raise Conflict("Ce module est indispensable : il ne peut pas être désactivé.")
    active = enabled_keys()
    if enabled:
        missing = [REGISTRY[d] for d in module.depends if d not in active]
        if missing:
            names = ", ".join(m.label[0] for m in missing)
            raise Conflict(f"Activez d'abord : {names}.")
    else:
        dependents = [m for m in REGISTRY.values() if key in m.depends and m.key in active]
        if dependents:
            names = ", ".join(m.label[0] for m in dependents)
            raise Conflict(f"Désactivez d'abord les modules qui en dépendent : {names}.")
    db.execute("UPDATE modules SET enabled = ?, updated_at = ? WHERE key = ?", (int(enabled), db.now_iso(), key))


def enable_all() -> None:
    """Mode démonstration : tous les modules actifs."""
    load()
    db.execute("UPDATE modules SET enabled = 1, updated_at = ?", (db.now_iso(),))


def set_selection(keys: object) -> None:
    """Assistant d'installation : active exactement les modules choisis (et leurs dépendances)."""
    if not isinstance(keys, (list, tuple, set)):
        raise ValueError("Liste de modules invalide.")
    modules = load()
    wanted = {k for k in keys if isinstance(k, str) and k in modules}
    pending = list(wanted)
    while pending:  # les dépendances suivent
        for dep in modules[pending.pop()].depends:
            if dep not in wanted:
                wanted.add(dep)
                pending.append(dep)
    now = db.now_iso()
    with db.connect() as conn:
        for key, module in modules.items():
            conn.execute("UPDATE modules SET enabled = ?, updated_at = ? WHERE key = ?",
                         (int(module.core or key in wanted), now, key))


def describe() -> list[dict]:
    """État des modules pour Paramètres → Modules."""
    active = enabled_keys()
    out = []
    for module in ordered():
        dependents = [m.key for m in REGISTRY.values() if module.key in m.depends]
        out.append({
            "key": module.key, "slug": module.slug, "label": module.label, "description": module.description,
            "icon": module.icon, "core": module.core, "enabled": module.key in active,
            "depends": list(module.depends), "dependents": dependents, "default_enabled": module.default_enabled,
            "entities": [{"key": e.key, "label": e.plural} for e in module.entities],
            "pages": [{"slug": p.slug, "label": p.label} for p in module.pages if not p.admin_only],
        })
    return out
