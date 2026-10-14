# Architecture modulaire de Caffein

Caffein devient un ERP pour petites entreprises, découpé en **modules** : Accueil, Données techniques, Achats,
Ventes, Production, Logistique, RH, CRM, Projets, Comptabilité et Paramètres. Chaque module s'active ou se désactive
dans les paramètres, et chaque utilisateur ne voit que les modules auxquels il a droit.

Ce document décrit les principes, le contrat d'un module et la marche à suivre pour en ajouter un.

## Les principes

1. **Les données vivent dans des tables SQL.** Une entité métier = une table ; ses lignes (lignes de commande,
   composants d'une nomenclature…) = une autre table, reliée par une clé étrangère. Pas de liste cachée dans un champ JSON.
   Le JSON reste réservé aux journaux techniques (exécutions des scripts, emails) et aux préférences d'affichage.
2. **Le serveur calcule, l'interface affiche.** Totaux, niveaux de stock, besoins en composants, soldes de congés,
   indicateurs : tout est calculé en Python (ou par une vue SQL) et renvoyé prêt à afficher. L'interface ne fait
   aucun calcul métier.
3. **Un module est autonome.** Il déclare ses tables, ses écrans, ses droits, ses scripts et ses indicateurs dans
   un seul dossier. Ajouter un module ne modifie pas les autres.
4. **Rien ne casse.** Les migrations sont versionnées par module et jamais réécrites ; une instance existante garde
   ses données, ses adresses et ses accès.

## Les modules

| Module | Clé | Contenu | Dépend de |
|---|---|---|---|
| Accueil | `home` | tableau de bord (indicateurs de chaque module), « Mes vues » | — (toujours actif) |
| Données techniques | `technical` | articles, familles, nomenclatures, postes de charge, gammes | — |
| Achats | `purchases` | fournisseurs, commandes fournisseurs, réceptions | `technical` (articles, facultatif) |
| Ventes | `sales` | clients, devis et factures, commandes clients | — |
| Production | `production` | ordres de fabrication, besoins en composants, déclaration de production | `technical`, `stock` |
| Logistique | `stock` | entrepôts, mouvements de stock, niveaux de stock, alertes de réapprovisionnement | `technical` |
| RH | `hr` | services, salariés, absences et congés | — |
| CRM | `crm` | prospects, opportunités, actions commerciales | — |
| Projets | `projects` | projets, tâches, temps passés | — |
| Comptabilité | `accounting` | TVA, URSSAF, justificatifs | — |
| Paramètres | `settings` | entreprise, utilisateurs, rôles et droits, modules, automatisations | — (toujours actif) |

Les modules communiquent seulement par leurs services, et seulement si le module appelé est actif. Exemple :
réceptionner une commande fournisseur crée des entrées de stock **si** la Logistique est active ; sinon la commande
est simplement marquée reçue.

## Les droits

- **Activation d'un module** (Paramètres → Modules) : un module désactivé disparaît pour tout le monde ; ses routes
  répondent 404 et ses scripts ne tournent plus. Ses données restent en base. On ne peut pas désactiver un module dont
  un autre module actif dépend, ni activer un module sans ses dépendances.
- **Niveaux par module** : `aucun` (module masqué), `lecture`, `écriture` (créer, modifier, lancer les actions),
  `gestion` (en plus : supprimer, voir les données sensibles comme les salaires).
- **Rôles** (Paramètres → Rôles et droits) : un rôle est une grille module × niveau (« Commercial », « Acheteur »,
  « Comptable »…). Chaque utilisateur a un rôle.
- **Dérogations par utilisateur** : pour un module, on peut donner à une personne un niveau différent de son rôle,
  par exemple pour lui masquer un module ou lui donner plus de droits.
- **Administrateurs** : tous les droits sur les modules actifs, et seuls à accéder aux paramètres de l'instance.

Niveau effectif d'un utilisateur sur un module : module inactif → aucun ; administrateur → gestion ;
sinon dérogation de l'utilisateur, à défaut niveau de son rôle, à défaut aucun. Le serveur vérifie ce niveau
sur chaque route ; l'interface s'en sert seulement pour masquer ce qui est interdit.

## Le contrat d'un module

Un module est un paquet Python `backend/caffein/modules/<clé>/` qui expose `MODULE = Module(...)` :

```python
MODULE = Module(
    key="hr", slug="rh", label=("RH", "HR"), icon="Users", order=70,
    description=("Salariés, absences et congés", "Employees, absences and leave"),
    depends=(),                      # modules requis
    migrations=MIGRATIONS,           # [(1, "CREATE TABLE hr_employees …"), (2, …)]
    entities=ENTITIES,               # entités : écrans de liste et de fiche générés
    pages=PAGES,                     # navigation du module
    router=router,                   # routes propres (facultatif)
    jobs=(),                         # scripts planifiés du module
    kpis=kpis,                       # indicateurs pour l'accueil
    dashboard_sources=SOURCES,       # cartes proposées dans « Mes vues »
    seed_demo=seed_demo,             # données de démonstration
    reset_tables=("hr_absences", "hr_employees", "hr_departments"),
)
```

- **Migrations** : une liste `(version, sql)` propre au module, appliquée une fois et suivie dans la table
  `schema_migrations`. Les tables du module sont préfixées par sa clé (`hr_`, `stock_`…). Pour faire évoluer le schéma,
  on ajoute une version ; on ne modifie jamais une version publiée.
- **Entités** : une déclaration (table, champs typés, lignes enfants, actions, calculs) dont Caffein tire tout seul
  l'API (liste, recherche, tri, filtres, fiche, création, modification, suppression, actions) et les écrans.
  Types de champs : texte, texte long, email, téléphone, entier, décimal, montant, pourcentage, date, booléen,
  liste de choix, référence vers une autre entité, numéro automatique (`CF-2026-0001`).
- **Pages** : une page est soit une entité (écran généré), soit un composant React du registre de l'interface
  pour les écrans sur mesure (les factures, la TVA…).
- **Actions** : un bouton sur la fiche (« Réceptionner », « Lancer la fabrication », « Approuver »), avec le niveau
  requis et la condition d'affichage ; le traitement est une fonction Python du module.

Côté interface, un module **purement déclaratif n'a besoin d'aucun fichier** : les écrans, les libellés (français et
anglais) et la navigation viennent de `/api/meta`. Un module avec des écrans sur mesure ajoute un dossier
`frontend/src/modules/<clé>/` qui exporte ses composants et ses traductions, et une ligne dans
`frontend/src/modules/index.js`.

## Ajouter un module

1. Créer `backend/caffein/modules/<clé>/__init__.py` avec `MODULE = Module(...)`, ses migrations et ses entités.
2. L'ajouter à la liste `MODULES` de `backend/caffein/modules/__init__.py`.
3. Écrire ses tests dans `backend/tests/modules/test_<clé>.py`.

Au démarrage suivant, ses tables sont créées. Sur une instance existante, un nouveau module arrive **désactivé** :
l'administrateur l'active dans Paramètres → Modules. Sur une nouvelle installation, l'assistant propose les modules.

## Les instances existantes

La mise à jour est automatique et conserve tout :

- les modules Accueil, Ventes, Comptabilité et Paramètres reprennent les écrans existants ; les nouveaux modules
  arrivent désactivés ;
- les membres reçoivent le rôle « Équipe (accès complet) », qui leur donne les mêmes accès qu'avant ;
- les lignes des factures et devis, jusqu'ici dans un champ JSON, sont copiées dans la table `invoice_lines` ;
- les anciennes adresses (`/factures`, `/tva`, `/urssaf`, `/documents`, `/automatisations`, `/vues`) redirigent vers
  les nouvelles, et les liens envoyés aux clients (`/f/…`) ne changent pas.
