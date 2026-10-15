# Architecture modulaire de Caffein

Caffein est un ERP pour petites entreprises, découpé en **modules** : Accueil, Données techniques, RH, Achats, Ventes,
CRM, Production, Logistique, Projets, Qualité, Maintenance, Comptabilité et Paramètres. Chaque module s'active ou se
désactive dans les paramètres, et chaque utilisateur ne voit que les modules auxquels il a droit.

Ce document décrit les principes, le contrat d'un module et la marche à suivre pour en ajouter un.

## Les principes

1. **Les données vivent dans des tables SQL.** Une entité métier = une table ; ses lignes (lignes de commande,
   composants d'une nomenclature…) = une autre table, reliée par une clé étrangère. Pas de liste cachée dans un champ JSON.
   Le JSON reste réservé aux journaux techniques (exécutions des scripts, emails) et aux préférences d'affichage.
2. **Le serveur calcule, l'interface affiche.** Totaux, coûts de revient, niveaux de stock, besoins en composants,
   soldes de congés, indicateurs : tout est calculé en Python (ou par une vue SQL) et renvoyé prêt à afficher. Pendant
   une saisie, l'interface demande les totaux au serveur (`/preview`) : elle ne fait aucun calcul métier.
3. **Un module est autonome.** Il déclare ses tables, ses écrans, ses droits, ses scripts et ses indicateurs dans
   un seul dossier. Ajouter un module ne modifie pas les autres.
4. **Rien ne casse.** Les migrations sont versionnées par module et jamais réécrites ; une instance existante garde
   ses données, ses adresses et ses accès. Un module désactivé disparaît sans rien emporter.

## Les modules

| Module | Clé | Adresse | Contenu | Dépend de |
|---|---|---|---|---|
| Accueil | `home` | `/` | chiffres clés de chaque module, raccourcis, échéances, activité, « Mes vues » | — (toujours actif) |
| Données techniques | `technical` | `/donnees-techniques` | articles, familles, nomenclatures, postes de charge, gammes, coûts de revient | — |
| RH | `hr` | `/rh` | services, salariés, absences et congés | — |
| Achats | `purchases` | `/achats` | fournisseurs, commandes fournisseurs, réceptions | — |
| Ventes | `sales` | `/ventes` | clients, devis et factures, commandes clients | — |
| CRM | `crm` | `/crm` | prospects, opportunités, actions commerciales | — |
| Production | `production` | `/production` | ordres de fabrication, besoins en composants, charge des postes | `technical`, `stock` |
| Logistique | `stock` | `/logistique` | entrepôts, mouvements, stock par article, réapprovisionnement | `technical` |
| Projets | `projects` | `/projets` | projets, tâches, temps passés, facturation des temps | — |
| Qualité | `quality` | `/qualite` | non-conformités, actions correctives et préventives | — |
| Maintenance | `maintenance` | `/maintenance` | équipements, interventions préventives et correctives | — |
| Comptabilité | `accounting` | `/comptabilite` | TVA, URSSAF, justificatifs | — |
| Paramètres | `settings` | `/parametres` | compte, entreprise, utilisateurs, rôles et droits, modules, automatisations | — (toujours actif) |

Les modules communiquent seulement par leurs **services** et leurs **événements**, et seulement si le module concerné
est actif. Exemple : livrer une commande client annonce `sales.order_delivered` ; la Logistique, si elle est active,
sort les articles du stock ; sinon la commande est simplement livrée.

## Les droits

- **Activation d'un module** (Paramètres → Modules) : un module désactivé disparaît pour tout le monde ; ses routes
  répondent 404 et ses scripts ne tournent plus. Ses données restent en base. On ne peut pas désactiver un module dont
  un autre module actif dépend, ni activer un module sans ses dépendances.
- **Niveaux par module** : `aucun` (module masqué), `lecture`, `écriture` (créer, modifier, lancer les actions),
  `gestion` (en plus : supprimer, voir les données sensibles comme les salaires, actions réservées).
- **Rôles** (Paramètres → Rôles et droits) : un rôle est une grille module × niveau (« Commercial », « Acheteur »,
  « Comptable »…), plus un niveau par défaut pour les autres modules (et ceux ajoutés plus tard).
- **Dérogations par utilisateur** : pour un module, on peut donner à une personne un niveau différent de son rôle.
- **Administrateurs** : tous les droits sur les modules actifs, et seuls à accéder aux paramètres de l'instance.

Niveau effectif d'un utilisateur sur un module : module inactif → aucun ; administrateur → gestion ;
sinon dérogation de l'utilisateur, à défaut niveau de son rôle pour ce module, à défaut niveau par défaut du rôle.
L'Accueil est toujours visible ; les Paramètres sont en lecture pour les membres (leur compte, les automatisations
de leurs modules). Le serveur vérifie ce niveau sur chaque route ; l'interface s'en sert seulement pour masquer.

## Le contrat d'un module

Un module est un paquet Python `backend/caffein/modules/<clé>/` qui expose `MODULE = Module(...)`
(`caffein/core/modules.py`) :

```python
MODULE = Module(
    key="hr", slug="rh", label=("RH", "HR"), icon="Users", order=20,
    description=("Salariés, absences et congés", "Employees, absences and leave"),
    depends=(),                      # modules requis
    default_enabled=True,            # actif sur une nouvelle installation (l'assistant propose de décocher)
    migrations=MIGRATIONS,           # [(1, "CREATE TABLE hr_employees …"), (2, …)]
    entities=ENTITIES,               # entités : écrans de liste et de fiche générés, API /api/data/hr/…
    pages=PAGES,                     # navigation du module (onglets)
    router=router,                   # routes propres (facultatif) : core.deps.module_router("hr")
    jobs=(),                         # scripts planifiés du module (noms dans jobs.JOBS)
    kpis=[Kpi(...)],                 # chiffres clés pour l'accueil
    shortcuts=[Shortcut(...)],       # raccourcis de l'accueil
    events={"sales.order_delivered": handler},   # réactions aux événements des autres modules
    references=[],                   # colonnes hors entités qui désignent une fiche (voir « Références »)
    seed_demo=seed_demo,             # données de démonstration
    reset_tables=("hr_absences", "hr_employees", "hr_departments"),  # vidées par la réinitialisation, enfants d'abord
)
```

### Migrations et tables

- Une liste `(version, sql)` propre au module, appliquée une fois et suivie dans `schema_migrations`. Pour faire
  évoluer le schéma, on **ajoute** une version ; on ne modifie jamais une version publiée.
- Tables préfixées par la clé du module (`hr_`, `stock_`…) ; `id INTEGER PRIMARY KEY AUTOINCREMENT` ;
  textes `NOT NULL DEFAULT ''` ; nombres et dates nullables ; `created_at` et `updated_at` (remplis par le moteur).
- Lignes enfants : `<parent>_id … REFERENCES <parent>(id) ON DELETE CASCADE` et `position INTEGER NOT NULL DEFAULT 0`.
- **Pas de clé étrangère vers la table d'un autre module** : la référence est un `INTEGER` simple, vérifiée par le
  moteur quand le module visé est actif. Les clés étrangères restent à l'intérieur d'un module.
- Une vue SQL peut porter une consultation (niveaux de stock…) : l'entité est alors `readonly=True` et la vue a une
  colonne `id` stable.

### Entités (`caffein/core/entities.py`)

Une entité déclare une table, ses champs, ses lignes, ses actions et ses calculs ; Caffein en tire l'API
(`/api/data/<module>/<entité>` : liste, recherche, tri, filtres, fiche, création, modification, suppression, actions,
aperçu des calculs, choix des références, export tableur `…/export`) et les écrans (liste, fiche dans un tiroir).

**Champs** — `Field(name, label, type, …)` :

| Type | Valeur | Remarques |
|---|---|---|
| `text`, `longtext`, `email`, `phone` | texte | `maxlength` (200 par défaut, 5000 pour `longtext`) |
| `int`, `decimal`, `money`, `percent` | nombre | `min`, `max` ; « 1 250,50 » accepté ; `money` arrondi à 2 décimales ; `percent` : 20 = 20 % |
| `date` | `AAAA-MM-JJ` | `default=_today` (fonction) pour la date du jour |
| `bool` | oui / non | |
| `enum` | une valeur de `choices` | `choices=(("draft", ("Brouillon", "Draft")), ("done", ("Terminé", "Done"), "good"))` : le 3e élément (facultatif) colore le badge : `good`, `warn`, `bad`, `info`, `accent`, `outline` |
| `ref` | id d'une fiche | `ref="technical.articles"` ; `fill={"description": "name", "unit_price": "sale_price"}` recopie des champs de la fiche choisie |
| `code` | numéro automatique | `prefix="CF"` → `CF-2026-0001` ; `yearly=False` → `ART-0001` |

Options : `required`, `unique` (insensible à la casse), `default` (valeur ou fonction), `readonly` (rempli par le
serveur), `computed` (pas une colonne : calculé par `compute`), `hidden` (lu avec la fiche, jamais affiché),
`sensitive` (visible et modifiable seulement au niveau gestion), `list` (colonne de la liste), `search`, `filter`
(`enum`, `bool`, `ref`), `help` (aide sous le champ), `width="full"`.

**Lignes** — `Child(key, label, table, fk, fields, min_rows=0, max_rows=500)` : enregistrées avec la fiche, dans la même
transaction. Des lignes dont tous les champs sont `readonly`/`computed` (besoins calculés…) ne se saisissent pas.

**Actions** — `Action(key, label, run, when=…, level=WRITE, confirm=(fr, en), style="primary"|"danger", icon)` : un
bouton de la fiche. `run(row, payload, user)` fait le traitement (et peut renvoyer un message) ; `when(row)` décide
s'il s'affiche ; `level=MANAGE` réserve l'action (validation d'un congé…).

**Crochets de l'entité** :

- `compute(rows)` : ajoute les champs calculés. Reçoit des fiches **avec** leurs lignes (fiche, aperçu de saisie) ou
  **sans** (liste) : dans ce cas, calculer par une requête groupée sur tous les `id`.
- `prepare(values, existing)` : ajuste les valeurs avant contrôle (signe d'une quantité, nom complet…).
- `validate(values, existing)` : contrôles métier ; `ValueError("Champ : message.")` → erreur 400 affichée.
- `locked(row)` : message si la fiche ne se modifie plus (commande confirmée…) ; les actions restent possibles.
- `before_delete(row)`, `after_save(row_id, created)`, `delete_level` (gestion par défaut), `readonly` (vue SQL).

**Références** : une fiche utilisée ailleurs ne se supprime pas (409, « utilisée ailleurs (commandes clients : 3) »).
Les champs `ref` de toutes les entités sont trouvés tout seuls, même dans un module désactivé ; une colonne hors
entité se déclare dans `Module.references` : `("invoice_lines", "article_id", "technical.articles", ("Factures", "Invoices"))`.
Un champ `ref` vers un module désactivé disparaît des écrans et de l'API.

**Messages d'erreur** : en français, commençant par le libellé du champ (« Quantité : elle doit être positive. »).

### Pages, chiffres clés, raccourcis

- `Page(slug, label, entity="hr.employees" | component="sales.invoices", icon, admin_only, min_level)` : une page
  est un écran généré (entité) ou un écran sur mesure du registre de l'interface. Adresse : `/<slug du module>/<slug>`.
- `Kpi(key, label, compute, unit="count"|"money"|"minutes"|"percent"|"days", foot=("{n} facture(s)", "{n} invoice(s)"),
  icon, path, alert=lambda d: …)` : `compute()` renvoie `{"value": …, "count": …}` ; `path` peut porter un filtre
  (`/logistique/stock?f_status=reorder`). Chaque chiffre clé s'affiche sur l'accueil et devient une carte possible
  de « Mes vues » (« montre-moi les articles à réapprovisionner ») pour qui peut consulter le module.
- `Shortcut(key, label, path, icon, level=WRITE)` : bouton de l'accueil (`?new=1` ouvre une fiche vierge, et
  `?new=1&client_id=3` la préremplit).

### Événements (`caffein/core/events.py`)

Un module annonce ce qui se passe avec `events.emit(nom, données)` ; les modules **actifs** abonnés (`Module.events`)
réagissent, dans l'ordre des dépendances, et peuvent renvoyer un message affiché à l'utilisateur. Une erreur d'un
abonné annule l'action : émettre **avant** d'enregistrer le changement d'état. Un abonné doit être idempotent
(la Logistique note le document d'origine et ne le compte jamais deux fois).

| Événement | Émis par | Données | Abonnés |
|---|---|---|---|
| `sales.order_confirmed` | Ventes (confirmer une commande) | `order_id`, `code`, `lines` | — |
| `sales.order_delivered` | Ventes (livrer) | `order_id`, `code`, `date`, `lines: [{article_id, description, quantity, unit_price}]` | Logistique (sorties) |
| `purchases.order_received` | Achats (réceptionner) | `order_id`, `code`, `date`, `warehouse_id` (facultatif), `lines: [{article_id, description, quantity, unit_price}]` | Logistique (entrées au coût d'achat) |
| `production.order_completed` | Production (déclarer la fabrication) | `order_id`, `code`, `date`, `article_id`, `quantity`, `warehouse_id` (facultatif), `components: [{article_id, quantity}]` | Logistique (entrée du produit, consommation des composants) |

### Services partagés

- **Données techniques** (`modules/technical/services.py`) : `article(id)`, `is_stocked(id)`, `active_bom(id)`,
  `components_for(article_id, quantité)` (besoins, pertes comprises), `active_routing(id)`, `cost_price(id)`
  (coût de revient : achat, sinon matière + gamme, de proche en proche).
- **Logistique** (`modules/stock/services.py`) : `on_hand(article_id, warehouse_id=None)`, `default_warehouse_id()`,
  `post(kind, lignes, sign=…, reference=…, date=…, source=…)`.
- **Ventes** (`caffein/services.py`) : `create_invoice({...})` (devis ou facture brouillon), `create_client({...})`.

Appeler un service d'un autre module seulement s'il est actif (`core.modules.is_enabled("stock")`), ou s'il est
déclaré dans `depends`.

Champs des entités partagées sur lesquels les autres modules s'appuient :

- `technical.articles` (`technical_articles`) : `code`, `name` (titre), `kind` (`goods`, `raw`, `semi`, `finished`,
  `service`), `unit`, `sale_price`, `purchase_price`, `vat_rate`, `min_stock`, `reorder_qty`, `active` ;
- `sales.clients` (`clients`) : `name` (titre), `email`, `city` ;
- `purchases.suppliers` (`purchases_suppliers`) : `name` (titre), `email` ;
- `hr.employees` (`hr_employees`) : `full_name` (titre), `email`, `department_id` ;
- `technical.workcenters` (`technical_workcenters`) : `name` (titre), `hourly_cost`, `capacity_hours`.

### Interface

Un module **purement déclaratif n'a besoin d'aucun fichier dans l'interface** : navigation, écrans, libellés
(français et anglais) et droits viennent de `/api/meta`. Les icônes se choisissent dans la liste de
`frontend/src/lib/icons.js` (un nom inconnu affiche une icône générique).

Un module avec des écrans sur mesure ajoute `frontend/src/modules/<clé>/index.js`, qui exporte
`{ components: { '<clé>.<écran>': lazy(() => import('./Ecran')) }, translations: { … } }`, et l'ajoute à la liste de
`frontend/src/modules/index.js`. Les écrans génériques (`components/entity/`) sont réutilisables dans un écran sur mesure.

## Ajouter un module

1. Créer `backend/caffein/modules/<clé>/__init__.py` avec `MODULE = Module(...)`, ses migrations et ses entités.
2. L'ajouter à la liste `MODULES` de `backend/caffein/modules/__init__.py`.
3. Écrire ses tests dans `backend/tests/modules/test_<clé>.py` (outils communs : `tests/modules/helpers.py`).

Le **contrat** (`backend/tests/test_module_contract.py`) vérifie ensuite le nouveau module sans rien écrire : clé,
adresse et libellés, icônes et écrans connus de l'interface, tables conformes aux entités et vidées par la
réinitialisation, listes, tris, filtres, exports, fiches et aperçus sur les données de démonstration (chaque entité
en a), chiffres clés calculables sur une base vide, rôle « Lecture seule » qui ne modifie rien, et surtout
désactivation du module sans casser les autres.

Au démarrage suivant, ses tables sont créées. Sur une instance existante, un nouveau module arrive **désactivé** :
l'administrateur l'active dans Paramètres → Modules. Sur une nouvelle installation, l'assistant propose les modules.

Exemples à suivre : `modules/sales/entities.py` (commande client : lignes, actions, événement),
`modules/technical/` (référentiel, coûts calculés, services), `modules/stock/` (vues SQL, abonnements aux événements).

## Les instances existantes

La mise à jour est automatique et conserve tout :

- les modules Accueil, Ventes, Comptabilité et Paramètres reprennent les écrans existants ; les nouveaux modules
  arrivent désactivés ;
- les membres reçoivent le rôle « Équipe (accès complet) », qui leur donne les mêmes accès qu'avant ;
- les lignes des factures et devis, jusqu'ici dans un champ JSON, sont copiées dans la table `invoice_lines` ;
- les anciennes adresses (`/factures`, `/tva`, `/urssaf`, `/documents`, `/automatisations`, `/vues`) redirigent vers
  les nouvelles, et les liens envoyés aux clients (`/f/…`) ne changent pas.
