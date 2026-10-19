# Ajouter un module à Caffein, pas à pas

Ce guide s'adresse à toute personne qui a téléchargé Caffein et veut lui ajouter un module : un suivi des véhicules,
des contrats, des chantiers, des prêts de matériel… Il suffit de connaître un peu de Python. **Pas besoin d'écrire de
React** : listes, fiches, recherche, filtres, export tableur, droits et traduction anglaise sont générés à partir de
la déclaration Python.

On construit ici, de bout en bout, un module **Flotte** (les véhicules de l'entreprise et leurs contrôles techniques).
Comptez une demi-heure. La référence complète (tous les types de champs, les crochets, les événements) est dans
[modules.md](modules.md) ; ce guide renvoie vers elle quand c'est utile.

## Sommaire

1. [Préparer son poste](#1-préparer-son-poste)
2. [Choisir la clé et l'adresse du module](#2-choisir-la-clé-et-ladresse-du-module)
3. [Créer le dossier du module](#3-créer-le-dossier-du-module)
4. [Déclarer la table](#4-déclarer-la-table)
5. [Déclarer l'entité : les champs et les écrans](#5-déclarer-lentité--les-champs-et-les-écrans)
6. [Déclarer le module](#6-déclarer-le-module)
7. [L'enregistrer dans Caffein](#7-lenregistrer-dans-caffein)
8. [Le voir dans l'interface](#8-le-voir-dans-linterface)
9. [Le tester](#9-le-tester)
10. [Aller plus loin](#10-aller-plus-loin)
11. [Partager son module](#11-partager-son-module)
12. [En cas de souci](#12-en-cas-de-souci)

## 1. Préparer son poste

Il faut Python ≥ 3.10 et Node.js ≥ 18 (voir [CONTRIBUTING.md](../CONTRIBUTING.md)).

```bash
git clone https://github.com/moreauremi/caffein.git
cd caffein
./start.sh --demo     # une première fois : installe tout, crée une instance de démonstration
```

Arrêtez-le (Ctrl+C), puis travaillez avec le rechargement à chaud :

```bash
./dev.sh --demo       # API Python sur :8000, interface sur http://localhost:5173
```

Chaque fois que vous enregistrez un fichier Python, le serveur redémarre tout seul.

## 2. Choisir la clé et l'adresse du module

Un module a trois noms, à choisir une fois pour toutes (ils finissent dans la base et dans les adresses) :

| Nom | Exemple | Règle |
|---|---|---|
| **Clé** | `fleet` | en anglais, minuscules, sans espace ; préfixe de toutes ses tables (`fleet_…`) |
| **Adresse** | `flotte` | en français, sans accent ; l'écran sera sur `/flotte/…` |
| **Libellé** | « Flotte » / « Fleet » | toujours la paire français, anglais |

La clé et l'adresse doivent être libres : regardez le tableau des modules existants dans [modules.md](modules.md#les-modules).

## 3. Créer le dossier du module

Un module est un dossier Python dans `backend/caffein/modules/`. Pour un petit module, un seul fichier suffit :

```
backend/caffein/modules/fleet/
└── __init__.py
```

Ouvrez `__init__.py` et commencez par l'en-tête et les imports :

```python
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Flotte : les véhicules de l'entreprise et leurs contrôles techniques."""

from __future__ import annotations

from datetime import timedelta

from ... import db
from ...core.entities import Entity, Field, save_row
from ...core.modules import MANAGE, Kpi, Module, Page, Shortcut
from ...utils import parse_date, today
```

## 4. Déclarer la table

Les données vivent dans des tables SQL. Un module décrit ses tables dans une liste de **migrations** numérotées : Caffein
applique chaque version une seule fois, au démarrage.

```python
MIGRATIONS = [(1, """
CREATE TABLE IF NOT EXISTS fleet_vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    plate TEXT NOT NULL DEFAULT '',
    mileage INTEGER,
    next_inspection TEXT,
    status TEXT NOT NULL DEFAULT 'available',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
""")]
```

Les conventions à respecter :

- tables préfixées par la clé du module (`fleet_`) ;
- `id INTEGER PRIMARY KEY AUTOINCREMENT`, et `created_at` / `updated_at` (remplis par Caffein) ;
- textes `NOT NULL DEFAULT ''`, nombres et dates nullables (une date est un texte `AAAA-MM-JJ`) ;
- **une migration publiée ne se modifie plus jamais** : pour changer le schéma plus tard, on ajoute une version
  (voir [Ajouter un champ plus tard](#ajouter-un-champ-plus-tard)).

## 5. Déclarer l'entité : les champs et les écrans

Une **entité** relie une table à ses champs. Caffein en tire l'API (`/api/data/fleet/vehicles`) et les écrans.

```python
STATUSES = (("available", ("Disponible", "Available"), "good"), ("in_use", ("En mission", "In use"), "info"),
            ("garage", ("Au garage", "At the garage"), "warn"))


def _days_left(rows: list[dict]) -> None:
    """Calcul en Python : jours avant le prochain contrôle technique (négatif = en retard)."""
    for row in rows:
        due = parse_date(row.get("next_inspection"))
        row["days_left"] = (due - today()).days if due else None


VEHICLES = Entity(
    module="fleet", name="vehicles", table="fleet_vehicles", label=("Véhicule", "Vehicle"),
    plural=("Véhicules", "Vehicles"), title="name", subtitle="plate", order_by="name COLLATE NOCASE",
    icon="Car", board="status", compute=_days_left,
    fields=[
        Field("code", ("Numéro", "Number"), type="code", prefix="VEH", yearly=False, readonly=True, list=True),
        Field("name", ("Véhicule", "Vehicle"), required=True, list=True, search=True),
        Field("plate", ("Immatriculation", "Plate"), list=True, search=True, maxlength=12),
        Field("mileage", ("Kilométrage", "Mileage"), type="int", min=0, max=2_000_000),
        Field("next_inspection", ("Prochain contrôle technique", "Next inspection"), type="date", list=True),
        Field("status", ("Statut", "Status"), type="enum", choices=STATUSES, default="available", list=True,
              filter=True),
        Field("days_left", ("Jours avant le contrôle", "Days to inspection"), type="int", computed=True, list=True),
    ],
)
```

Ce que fait chaque réglage :

| Réglage | Effet à l'écran |
|---|---|
| `title="name"`, `subtitle="plate"` | le titre et le sous-titre d'une fiche, et ce qui s'affiche quand un autre écran la cite |
| `list=True` | le champ est une colonne de la liste |
| `search=True` | la barre de recherche cherche dans ce champ |
| `filter=True` | un filtre est proposé au-dessus de la liste (champs à choix, oui/non, références) |
| `type="code", prefix="VEH"` | numéro automatique non modifiable : `VEH-0001`, `VEH-0002`… |
| `type="enum", choices=…` | liste de choix ; le 3e élément colore le badge (`good`, `warn`, `bad`, `info`…) |
| `board="status"` | une vue « Tableau » à côté de la liste, une colonne par statut |
| `computed=True` + `compute=…` | champ calculé par le serveur, jamais saisi (ici les jours avant le contrôle) |
| `min`, `max`, `required`, `maxlength` | contrôles faits par le serveur, avec un message clair en cas d'erreur |

Tous les types de champs (`money`, `percent`, `bool`, `longtext`, `ref` vers une fiche d'un autre module…) sont
décrits dans [modules.md](modules.md#entités-caffeincoreentitiespy).

> **La règle d'or de Caffein : le serveur calcule, l'interface affiche.** Un total, un délai, un solde se calculent
> dans `compute`, jamais dans le navigateur.

## 6. Déclarer le module

Il reste à rassembler le tout dans `MODULE`, avec un chiffre clé pour l'accueil, un raccourci et des données de
démonstration :

```python
def _to_inspect() -> dict:
    limit = (today() + timedelta(days=30)).isoformat()
    n = db.fetch_one("SELECT COUNT(*) AS n FROM fleet_vehicles WHERE next_inspection <= ?", (limit,))["n"]
    return {"value": n, "count": n}


def _seed_demo() -> None:
    for name, plate, days in (("Kangoo de livraison", "GA-123-BC", 12), ("Clio de l'atelier", "FB-456-DE", 200)):
        save_row(VEHICLES, {"name": name, "plate": plate, "next_inspection": (today() + timedelta(days=days)).isoformat()},
                 MANAGE)


MODULE = Module(
    key="fleet", slug="flotte", label=("Flotte", "Fleet"), icon="Car", order=88,
    description=("Les véhicules de l'entreprise et leurs contrôles techniques.", "Company vehicles and their inspections."),
    migrations=MIGRATIONS, entities=[VEHICLES],
    pages=[Page("vehicules", ("Véhicules", "Vehicles"), entity="fleet.vehicles", icon="Car")],
    kpis=[Kpi("to_inspect", ("Véhicules à faire contrôler", "Vehicles due for inspection"), _to_inspect, icon="Car",
              path="/flotte/vehicules", alert=lambda d: d["value"] > 0)],
    shortcuts=[Shortcut("new_vehicle", ("Nouveau véhicule", "New vehicle"), "/flotte/vehicules?new=1", icon="Car")],
    seed_demo=_seed_demo, reset_tables=("fleet_vehicles",),
)
```

| Paramètre | Rôle |
|---|---|
| `order` | place dans la barre latérale : les modules existants vont de 0 (Accueil) à 90 (Comptabilité), Paramètres reste en dernier |
| `icon` | un nom de la liste de [`frontend/src/lib/icons.js`](../frontend/src/lib/icons.js) (icônes lucide) ; un nom inconnu affiche une icône générique |
| `pages` | les onglets du module ; `Page("vehicules", …)` sera à l'adresse `/flotte/vehicules` |
| `kpis` | les chiffres clés de l'accueil ; `alert` met la carte en avant (ici dès qu'un contrôle approche) |
| `shortcuts` | les boutons de l'accueil ; `?new=1` ouvre directement une fiche vierge |
| `seed_demo` | les données de l'instance de démonstration : **obligatoire en pratique**, le contrat des modules s'en sert pour tester les écrans |
| `reset_tables` | les tables vidées par la réinitialisation des données, lignes enfants d'abord |
| `depends` | les modules requis, par exemple `("technical",)` pour utiliser les articles |
| `default_enabled` | actif ou non sur une nouvelle installation (vrai par défaut) |

## 7. L'enregistrer dans Caffein

Ouvrez `backend/caffein/modules/__init__.py` et ajoutez le module à l'import et à la liste `MODULES` :

```python
from . import accounting, crm, fleet, home, hr, maintenance, production, projects, purchases, quality, sales, settings, stock, technical

MODULES = [
    home.MODULE,
    # …
    maintenance.MODULE,
    fleet.MODULE,
    accounting.MODULE,
    settings.MODULE,
]
```

L'ordre de la liste n'a pas d'importance : la navigation suit `order`, les migrations suivent `depends`.

## 8. Le voir dans l'interface

Au redémarrage, Caffein crée la table `fleet_vehicles`. Sur une instance qui existait déjà, **un nouveau module arrive
désactivé**, pour ne rien imposer à ses utilisateurs. Deux façons de l'activer :

- dans l'interface : **Paramètres → Modules**, puis activer « Flotte » ;
- en ligne de commande (depuis `backend/`) :

```bash
.venv.nosync/bin/python -m caffein modules enable fleet
```

Pour retrouver aussi ses données de démonstration, recréez le jeu de démonstration : il active tous les modules et
appelle chaque `seed_demo` (les comptes sont conservés, les données métier sont effacées) :

```bash
.venv.nosync/bin/python -m caffein seed --demo --reset
```

Rechargez http://localhost:5173 : « Flotte » apparaît dans la barre latérale, avec la liste des véhicules, la vue
Tableau par statut, la fiche, l'export tableur, le chiffre clé « Véhicules à faire contrôler » et le raccourci
« Nouveau véhicule » sur l'accueil. Basculez l'interface en anglais : les libellés suivent.

Les droits fonctionnent déjà aussi : dans **Paramètres → Rôles et droits**, chaque rôle a maintenant une ligne
« Flotte » (aucun, lecture, écriture, gestion).

## 9. Le tester

Caffein vérifie **tout seul** chaque module avec son contrat (`backend/tests/test_module_contract.py`) : déclaration,
tables conformes aux entités, écrans sur les données de démonstration, chiffres clés sur une base vide, rôle
« Lecture seule » qui ne modifie rien, désactivation du module sans casser les autres. Lancez-le :

```bash
cd backend
.venv.nosync/bin/python -m pytest -q tests/test_module_contract.py
```

Écrivez ensuite quelques tests pour la logique propre à votre module, dans `backend/tests/modules/test_fleet.py` :

```python
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Flotte : la logique propre au module (le contrat des modules vérifie le reste)."""

from datetime import timedelta

from caffein.utils import today

from .helpers import login_as, make_member

BASE = "/api/data/fleet/vehicles"


def test_vehicle_and_days_to_inspection(client):
    due = (today() + timedelta(days=10)).isoformat()
    vehicle = client.post(BASE, json={"name": "Trafic", "plate": "HC-789-FG", "next_inspection": due}).json()
    assert vehicle["code"].startswith("VEH-") and vehicle["days_left"] == 10 and vehicle["status"] == "available"
    assert client.post(BASE, json={"name": "Trafic", "mileage": -5}).json()["detail"] == "Kilométrage : 0 au minimum."
    kpi = next(k for k in client.get("/api/home").json()["kpis"] if k["key"] == "fleet.to_inspect")
    assert kpi["value"] == 2 and kpi["alert"] is True  # le Kangoo de la démonstration et le Trafic


def test_read_only_member(client):
    make_member("flotte@test.local", "readonly")
    reader = login_as("flotte@test.local")
    assert reader.get(BASE).status_code == 200 and reader.post(BASE, json={"name": "x"}).status_code == 403
```

Avant de proposer le module, lancez toutes les vérifications :

```bash
cd backend && .venv.nosync/bin/ruff check caffein tests && .venv.nosync/bin/python -m pytest -q
```

## 10. Aller plus loin

### Ajouter un champ plus tard

On **ajoute** une version de migration, on ne réécrit jamais la première. Exemple : le conducteur attitré, choisi
parmi les salariés du module RH.

```python
MIGRATIONS = [
    (1, """CREATE TABLE IF NOT EXISTS fleet_vehicles ( … );"""),   # inchangée
    (2, "ALTER TABLE fleet_vehicles ADD COLUMN driver_id INTEGER;"),
]
```

```python
Field("driver_id", ("Conducteur", "Driver"), type="ref", ref="hr.employees", list=True, filter=True),
```

Une référence vers un autre module est un simple `INTEGER`, **sans clé étrangère** : Caffein vérifie lui-même que la
fiche existe quand le module RH est actif. S'il est désactivé, le champ disparaît des écrans, sans erreur.

### Des lignes dans une fiche

Pour un carnet d'entretien par véhicule, une table enfant reliée par une clé étrangère, et un `Child` dans l'entité :

```python
(3, """
CREATE TABLE IF NOT EXISTS fleet_services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id INTEGER NOT NULL REFERENCES fleet_vehicles(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    day TEXT,
    label TEXT NOT NULL DEFAULT '',
    cost REAL
);
"""),
```

```python
from ...core.entities import Child

VEHICLES = Entity(
    # …
    children=[Child("services", ("Entretiens", "Services"), table="fleet_services", fk="vehicle_id", fields=[
        Field("day", ("Date", "Date"), type="date"),
        Field("label", ("Intervention", "Work done"), required=True),
        Field("cost", ("Coût", "Cost"), type="money", min=0),
    ])],
)
```

Pensez à ajouter la table enfant **en premier** dans `reset_tables=("fleet_services", "fleet_vehicles")`.

### Un bouton d'action sur la fiche

```python
from ...core.entities import Action


def _to_garage(row: dict, payload: dict, user: dict) -> str:
    db.update("fleet_vehicles", row["id"], {"status": "garage", "updated_at": db.now_iso()})
    return f"{row['name']} part au garage."


VEHICLES = Entity(
    # …
    actions=[Action("garage", ("Envoyer au garage", "Send to the garage"), _to_garage,
                    when=lambda r: r.get("status") != "garage", icon="Wrench")],
)
```

`when` décide quand le bouton s'affiche, `level=MANAGE` le réserve aux gestionnaires, `confirm=(fr, en)` demande une
confirmation. Pour refuser une action, levez `ValueError("Champ : message.")` : le message s'affiche tel quel.

### Contrôles métier, fiches verrouillées

Sur l'entité : `validate(values, existing)` pour les règles (« la date de fin suit la date de début »),
`prepare(values, existing)` pour ajuster une valeur avant contrôle, `locked(row)` pour figer une fiche (commande
confirmée…). Détails dans [modules.md](modules.md#entités-caffeincoreentitiespy).

### Réagir à ce qui se passe ailleurs

Un module peut s'abonner aux **événements** des autres (une commande livrée, un achat réceptionné…) avec
`events={"sales.order_delivered": ma_fonction}` dans `Module(...)`. La liste des événements et leurs données est dans
[modules.md](modules.md#événements-caffeincoreeventspy).

### Un écran sur mesure

Les écrans générés suffisent dans la plupart des cas. Pour un écran particulier (un planning, une carte…), le
module ajoute un composant React dans `frontend/src/modules/<clé>/` et une `Page(…, component="fleet.planning")`.
Voir [modules.md](modules.md#interface) et les modules `sales` ou `accounting` comme exemples.

### Une tâche planifiée

Un relevé du matin, une alerte par email : un script dans `backend/caffein/jobs/` (décorateur `@job`), rattaché
au module par `jobs=("nom_du_script",)`. Il s'arrête tout seul quand le module est désactivé. Voir
[architecture.md](architecture.md).

## 11. Partager son module

- **Pour votre entreprise seulement** : gardez votre version (un fork, une branche). Si vous la proposez à d'autres
  personnes **via le réseau** (une instance en ligne pour des clients, un SaaS), la licence AGPL-3.0 vous demande de
  publier le code de cette version et de renseigner `CAFFEIN_SOURCE_URL` (voir la [licence](../README.md#licence)).
- **Pour tout le monde** : ouvrez d'abord un ticket pour présenter l'idée, puis une pull request (voir
  [CONTRIBUTING.md](../CONTRIBUTING.md)). Un module proposé doit passer le contrat, avoir ses tests, ses données de
  démonstration, ses libellés en français et en anglais, et une ligne dans le `CHANGELOG.md`.

## 12. En cas de souci

| Symptôme | Cause probable |
|---|---|
| Le module n'apparaît pas dans la barre latérale | il est désactivé (étape 8), ou votre rôle n'a aucun droit sur lui (Paramètres → Rôles et droits) |
| `Module déjà enregistré` ou `Adresse de module déjà utilisée` | la clé ou l'adresse est prise par un autre module |
| `Le module … dépend de modules inconnus` | une clé dans `depends` est mal écrite |
| `Le champ titre … n'est pas déclaré` | `title=` doit nommer un des `fields` |
| Le contrat échoue sur « tables » | la table ne correspond pas aux champs : une colonne manque, ou un champ non `computed` n'a pas de colonne |
| Le contrat échoue sur les écrans | l'entité n'a pas de données de démonstration (`seed_demo`) |
| Une icône générique s'affiche | le nom d'icône n'est pas dans `frontend/src/lib/icons.js` |
| La nouvelle colonne n'existe pas | la première migration a été modifiée au lieu d'ajouter une version : remettez-la comme avant et ajoutez `(2, "ALTER TABLE …")` |

Une question, un blocage ? Ouvrez un ticket sur [GitHub](https://github.com/moreauremi/caffein/issues).
