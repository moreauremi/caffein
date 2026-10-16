# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contrat des modules : tout module déclaré, présent ou à venir, est vérifié ici sans écrire de test.

Déclaration cohérente (adresses, libellés, icônes et écrans connus de l'interface), tables conformes aux
entités, listes, exports et fiches qui fonctionnent sur les données de démonstration, chiffres clés
calculables même sur une base vide, droits respectés, et surtout : chaque module se désactive sans casser
les autres. Voir docs/modules.md (« Ajouter un module »)."""

import importlib
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from caffein import auth, db
from caffein.core import entities
from caffein.core import modules as registry
from caffein.jobs import JOBS
from caffein.seed import _clear_tables, business_tables, seed

from .conftest import ADMIN, ensure_admin
from .modules.helpers import disable_module, login_as, make_member

MODULES = registry.ordered()
OPTIONAL = [m for m in MODULES if not m.core]
FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
UNITS = {"count", "money", "minutes", "percent", "days"}
TONES = {"good", "warn", "bad", "info", "accent", "outline"}
RESERVED = {"api", "login", "setup", "f", "app", "assets"}  # adresses déjà prises par l'application


def _label(value) -> bool:
    return isinstance(value, tuple) and len(value) == 2 and all(isinstance(s, str) and s.strip() for s in value)


def _frontend_icons() -> set[str] | None:
    path = FRONTEND / "lib" / "icons.js"
    if not path.exists():  # dépôt sans l'interface : contrôle impossible
        return None
    block = path.read_text(encoding="utf-8").split("export const ICONS = {", 1)[1].split("}", 1)[0]
    return {name.strip() for name in block.split(",") if name.strip()}


def _frontend_components() -> set[str] | None:
    """Écrans des modules réellement chargés par l'interface (src/modules/index.js)."""
    index = FRONTEND / "modules" / "index.js"
    if not index.exists():
        return None
    text = index.read_text(encoding="utf-8")
    imported = dict(re.findall(r"^import (\w+) from '\./(\w+)'", text, re.M))
    listed = {n.strip() for n in re.search(r"FRONTEND_MODULES = \[([^\]]*)\]", text).group(1).split(",") if n.strip()}
    found: set[str] = set()
    for name, folder in imported.items():
        if name in listed:
            found |= set(re.findall(r"'([a-z_]+\.[a-z_]+)'\s*:", (index.parent / folder / "index.js").read_text(encoding="utf-8")))
    return found


def _icons(module: registry.Module) -> set[str]:
    names = {module.icon, *(p.icon for p in module.pages), *(k.icon for k in module.kpis), *(s.icon for s in module.shortcuts)}
    for entity in module.entities:
        names |= {entity.icon, *(a.icon for a in entity.actions)}
    return {n for n in names if n}


def _columns(table: str) -> set[str]:
    with db.connect() as conn:
        return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


@pytest.fixture(scope="module")
def admin():
    """Une seule base de démonstration pour tout le fichier : les contrôles ne modifient pas les données."""
    db.init_db()
    seed(reset=True)
    auth._failures.clear()
    ensure_admin()
    from caffein.api.main import app

    with TestClient(app) as c:
        res = c.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
        assert res.status_code == 200, res.text
        yield c
    registry.enable_all()


# ═════════════════════════════════════════════════════════════════════════
# Déclaration
# ═════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("module", MODULES, ids=[m.key for m in MODULES])
def test_declaration(module):
    assert importlib.import_module(f"caffein.modules.{module.key}").MODULE is module, "MODULE dans caffein/modules/<clé>/"
    assert SLUG.match(module.slug) and module.slug not in RESERVED, module.slug
    assert _label(module.label) and _label(module.description)
    assert module.key not in module.depends and set(module.depends) <= set(registry.load())
    icons = _frontend_icons()
    if icons is not None:
        assert not _icons(module) - icons, f"icônes absentes de frontend/src/lib/icons.js : {_icons(module) - icons}"

    components = _frontend_components()
    own = {e.key for e in module.entities}
    slugs = [p.slug for p in module.pages]
    assert len(slugs) == len(set(slugs)), "pages en double"
    for page in module.pages:
        assert SLUG.match(page.slug) and _label(page.label), page.slug
        assert bool(page.entity) != bool(page.component), f"page {page.slug} : une entité ou un écran, pas les deux"
        if page.entity:
            assert page.entity in own, f"page {page.slug} : entité {page.entity} d'un autre module"
        elif components is not None:
            assert page.component in components, f"écran {page.component} inconnu de l'interface (frontend/src/modules)"

    names = [e.name for e in module.entities]
    assert len(names) == len(set(names))
    for entity in module.entities:
        assert entity.module == module.key and _label(entity.label) and _label(entity.plural)
        for fld in [*entity.fields, *(f for c in entity.children for f in c.fields)]:
            where = f"{entity.key}.{fld.name}"
            assert _label(fld.label), where
            assert fld.type != "ref" or fld.ref in entities.ENTITIES, f"{where} → entité inconnue {fld.ref}"
            for choice in fld.choices:
                assert _label(choice[1]) and (len(choice) == 2 or choice[2] in TONES), where
            if fld.fill:
                target = entities.ENTITIES[fld.ref]
                assert set(fld.fill.values()) <= {f.name for f in target.fields}, f"{where} : fill vers des champs inconnus"
        for child in entity.children:
            assert _label(child.label)
        actions = [a.key for a in entity.actions]
        assert len(actions) == len(set(actions)) and all(_label(a.label) for a in entity.actions), entity.key
        assert all(a.confirm is None or _label(a.confirm) for a in entity.actions)

    kpis = [k.key for k in module.kpis]
    assert len(kpis) == len(set(kpis)), "chiffres clés en double"
    for kpi in module.kpis:
        assert _label(kpi.label) and kpi.unit in UNITS and (kpi.foot is None or _label(kpi.foot)), kpi.key
        assert kpi.path is None or kpi.path.startswith("/"), kpi.key
    for shortcut in module.shortcuts:
        assert _label(shortcut.label) and shortcut.path.startswith("/") and shortcut.level in (1, 2, 3), shortcut.key
    assert set(module.jobs) <= set(JOBS), f"scripts inconnus : {set(module.jobs) - set(JOBS)}"
    for event, handler in module.events.items():
        assert re.match(r"^[a-z_]+\.[a-z_]+$", event) and callable(handler), event


def test_addresses_are_unique():
    paths = [p.path or f"/{m.slug}/{p.slug}" for m in MODULES for p in m.pages]
    assert len(paths) == len(set(paths)), sorted(p for p in paths if paths.count(p) > 1)
    tables = [t for m in MODULES for e in m.entities for t in (e.table, *(c.table for c in e.children))]
    assert len(tables) == len(set(tables)), "deux entités sur la même table"


# ═════════════════════════════════════════════════════════════════════════
# Tables et données de démonstration
# ═════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("module", MODULES, ids=[m.key for m in MODULES])
def test_tables_follow_declarations(admin, module):
    cleared = business_tables()
    for entity in module.entities:
        columns = _columns(entity.table)
        assert columns, f"table (ou vue) {entity.table} absente : migration manquante ?"
        missing = {f.name for f in entity.fields if not f.computed} - columns
        assert not missing, f"{entity.key} : colonnes absentes {missing}"
        if not entity.readonly:  # les vues n'ont rien à vider
            assert entity.table in cleared, f"{entity.table} absente de reset_tables : la réinitialisation la garderait"
        for child in entity.children:
            child_columns = _columns(child.table)
            assert {child.fk, "position"} <= child_columns, f"{child.table} : {child.fk} et position attendus"
            missing = {f.name for f in child.fields if not f.computed} - child_columns
            assert not missing, f"{entity.key}.{child.key} : colonnes absentes {missing}"
            if not entity.readonly:
                assert child.table in cleared and cleared.index(child.table) < cleared.index(entity.table), \
                    f"reset_tables : {child.table} avant {entity.table}"


@pytest.mark.parametrize("module", MODULES, ids=[m.key for m in MODULES])
def test_screens_work_on_demo_data(admin, module):
    meta = admin.get("/api/meta").json()
    for entity in module.entities:
        info = meta["entities"][entity.key]
        base = f"/api/data/{module.key}/{entity.name}"
        listing = admin.get(base)
        assert listing.status_code == 200, listing.text
        rows = listing.json()["rows"]
        assert rows, f"{entity.key} : aucune donnée de démonstration"
        assert admin.get(base, params={"q": "a"}).status_code == 200
        for fld in info["fields"]:
            if fld["sortable"]:
                for direction in ("asc", "desc"):
                    res = admin.get(base, params={"sort": fld["name"], "dir": direction})
                    assert res.status_code == 200, f"{entity.key} tri {fld['name']} : {res.text}"
            if fld["filter"]:
                value = fld["choices"][0]["value"] if fld.get("choices") else "1"
                res = admin.get(base, params={f"f_{fld['name']}": value})
                assert res.status_code == 200, f"{entity.key} filtre {fld['name']} : {res.text}"
        if entity.board:
            board = admin.get(f"{base}/board")
            assert board.status_code == 200, f"{entity.key} colonnes : {board.text}"
            assert sum(c["count"] for c in board.json()["columns"]) <= listing.json()["total"], entity.key
        export = admin.get(f"{base}/export")
        assert export.status_code == 200 and export.headers["content-type"].startswith("text/csv"), entity.key
        assert admin.get(f"{base}/options", params={"q": ""}).status_code == 200
        for row in rows[:3]:
            record = admin.get(f"{base}/{row['id']}")
            assert record.status_code == 200, f"{entity.key} #{row['id']} : {record.text}"
            if not entity.readonly:
                res = admin.post(f"{base}/preview", params={"id": row["id"]}, json=record.json())
                assert res.status_code == 200, f"{entity.key} aperçu #{row['id']} : {res.text}"


def test_kpis_and_home_on_demo_data(admin):
    home = admin.get("/api/home").json()
    shown = {(k["module"], k["key"]) for k in home["kpis"]}
    for module in MODULES:
        for kpi in module.kpis:
            assert (module.key, f"{module.key}.{kpi.key}") in shown, f"{module.key}.{kpi.key} absent de l'accueil"
    paths = {p["path"] or f"/{m['slug']}/{p['slug']}" for m in admin.get("/api/meta").json()["modules"] for p in m["pages"]}
    for kpi in home["kpis"]:
        assert kpi["path"] is None or kpi["path"].split("?")[0] in paths, f"{kpi['key']} mène à {kpi['path']}"
    for shortcut in home["shortcuts"]:
        assert shortcut["path"].split("?")[0] in paths, f"raccourci {shortcut['key']} mène à {shortcut['path']}"


# ═════════════════════════════════════════════════════════════════════════
# Droits
# ═════════════════════════════════════════════════════════════════════════
def test_read_only_role_reads_and_never_writes(admin):
    make_member("contrat-lecture@test.local", "readonly")
    reader = login_as("contrat-lecture@test.local")
    meta = reader.get("/api/meta").json()
    assert {m["key"] for m in meta["modules"]} == {k for k in registry.enabled_keys() if registry.get(k).pages}
    for key, info in meta["entities"].items():
        base = f"/api/data/{info['module']}/{info['name']}"
        assert not (info["can_create"] or info["can_edit"] or info["can_delete"]), key
        listing = reader.get(base)
        assert listing.status_code == 200, key
        assert reader.post(base, json={}).status_code == 403, key
        for row in listing.json()["rows"][:1]:
            assert reader.put(f"{base}/{row['id']}", json={}).status_code == 403, key
            assert reader.delete(f"{base}/{row['id']}").status_code == 403, key
            for action in info["actions"]:
                if action["level"] >= 2:
                    res = reader.post(f"{base}/{row['id']}/actions/{action['key']}", json={})
                    assert res.status_code == 403, f"{key} action {action['key']} : {res.status_code}"


# ═════════════════════════════════════════════════════════════════════════
# Désactiver un module ne casse rien
# ═════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("module", OPTIONAL, ids=[m.key for m in OPTIONAL])
def test_disabling_a_module_breaks_nothing(admin, module):
    try:
        disable_module(admin, module.key)
        off = {m.key for m in MODULES} - registry.enabled_keys()
        meta = admin.get("/api/meta").json()
        assert not off & {m["key"] for m in meta["modules"]}
        home = admin.get("/api/home")
        assert home.status_code == 200, home.text
        assert not [k for k in home.json()["kpis"] if k["module"] in off]
        slugs = {registry.get(k).slug for k in off}
        assert not [s for s in home.json()["shortcuts"] if s["path"].strip("/").split("/")[0] in slugs]
        assert admin.get("/api/dashboards").status_code == 200
        for key, info in meta["entities"].items():
            assert info["module"] not in off, key
            refs = [f for f in info["fields"] if f["type"] == "ref"]
            assert not [f for f in refs if f["ref"].split(".")[0] in off], f"{key} : référence vers un module désactivé"
            base = f"/api/data/{info['module']}/{info['name']}"
            listing = admin.get(base)
            assert listing.status_code == 200, f"{key} : {listing.text}"
            assert admin.get(f"{base}/export").status_code == 200, key
            for row in listing.json()["rows"][:2]:
                record = admin.get(f"{base}/{row['id']}")
                assert record.status_code == 200, f"{key} #{row['id']} : {record.text}"
                if not info["readonly"]:
                    res = admin.post(f"{base}/preview", params={"id": row["id"]}, json=record.json())
                    assert res.status_code == 200, f"{key} aperçu #{row['id']} : {res.text}"
        for entity in module.entities:
            assert admin.get(f"/api/data/{module.key}/{entity.name}").status_code == 404
    finally:
        registry.enable_all()


# ═════════════════════════════════════════════════════════════════════════
# Base vide (nouvelle installation) — en dernier : la base de démonstration est reconstruite ensuite
# ═════════════════════════════════════════════════════════════════════════
def test_everything_works_on_an_empty_base(admin):
    _clear_tables()
    try:
        for module in MODULES:
            for kpi in module.kpis:
                data = kpi.compute()
                assert isinstance(data, dict) and "value" in data, f"{module.key}.{kpi.key}"
                if kpi.alert:
                    kpi.alert(data)
        assert admin.get("/api/home").status_code == 200
        for key, info in admin.get("/api/meta").json()["entities"].items():
            base = f"/api/data/{info['module']}/{info['name']}"
            listing = admin.get(base)
            assert listing.status_code == 200 and listing.json()["total"] == 0, f"{key} : {listing.text}"
            assert admin.get(f"{base}/export").status_code == 200, key
            if not info["readonly"]:
                res = admin.post(f"{base}/preview", json={})
                assert res.status_code == 200, f"{key} aperçu d'une fiche vide : {res.text}"
    finally:
        seed(reset=True)
