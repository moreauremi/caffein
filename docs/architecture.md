# Architecture de Caffein

Ce document s'adresse aux personnes qui veulent comprendre ou modifier le code.

## Vue d'ensemble

```
Navigateur ──HTTP──▶ FastAPI (backend/caffein/api/main.py)
                       ├─ /api/meta         description de l'espace de l'utilisateur (modules, pages, entités, droits)
                       ├─ /api/data/*       moteur de données générique (entités déclarées par les modules)
                       ├─ /api/*            routes des modules (factures, TVA…) et du socle (compte, paramètres)
                       ├─ /*                interface React buildée (frontend/dist)
                       └─ planificateur     thread qui lance les scripts des modules actifs (jobs/)
                     SQLite (data/caffein.db) · documents (data/drive/) · boîte d'envoi (data/outbox/)
Services optionnels : Claude (IA), SMTP ou Resend (emails), IMAP (newsletters)
```

Un seul processus, une seule base. Le planificateur tourne dans le serveur : ne lancez pas plusieurs workers uvicorn.

Caffein est découpé en **modules** (Accueil, Données techniques, RH, Achats, Ventes, CRM, Production, Logistique,
Projets, Qualité, Maintenance, Comptabilité, Paramètres) qui s'activent et se règlent par utilisateur. Le contrat d'un
module, le moteur de données et les droits sont décrits dans [modules.md](modules.md).

## Backend (`backend/caffein/`)

| Module | Rôle |
|---|---|
| `core/` | socle des modules : registre et activation (`modules.py`), migrations des modules (`migrations.py`), droits (`permissions.py`), moteur de données (`entities.py`) et son API (`entity_api.py`), événements entre modules (`events.py`), description de l'espace (`meta.py`), dépendances FastAPI (`deps.py`) |
| `modules/<clé>/` | un paquet par module : `MODULE = Module(...)`, tables, entités, routes, chiffres clés, données de démonstration |
| `config.py` | variables d'environnement, chemins, constantes |
| `db.py` | connexion SQLite et **migrations du socle** (`MIGRATIONS`, `PRAGMA user_version`) ; chaque module a les siennes |
| `auth.py` | comptes, hachage scrypt, sessions côté serveur, limitation des tentatives |
| `services.py` | logique métier : clients, factures et devis, documents, tableaux de bord TVA et URSSAF |
| `fiscal.py` | taux URSSAF, périodes et échéances (valeurs indicatives à tenir à jour) |
| `ai.py` | appels à Claude (sorties structurées) et replis heuristiques hors-ligne |
| `dashboard.py` | « Mes vues » : catalogue de cartes, validation des descriptions, calcul des données, analyse locale, vues enregistrées ([détails](tableau-de-bord-ia.md)) |
| `crypto.py` | chiffrement AES-256-GCM des champs sensibles |
| `pdf_invoice.py` | rendu PDF des factures et devis (ReportLab) |
| `emailer.py`, `email_templates.py` | envoi (SMTP, Resend ou simulation) et gabarits HTML |
| `jobs/` | scripts d'automatisation (un fichier par script, décorateur `@job`) |
| `scheduler.py` | planification (toutes les N minutes, tous les jours à HH:MM) |
| `backup.py` | sauvegarde et restauration |
| `seed.py` | instance vierge et données de démonstration |
| `__main__.py` | ligne de commande `caffein …` |

### Accès et sécurité

- Routes publiques (santé, installation, connexion, page publique d'une facture), routes du socle (utilisateur connecté),
  routes de chaque module et moteur de données. Chaque route d'un module vérifie que le module est actif (sinon 404) et
  le niveau de l'utilisateur sur ce module (lecture pour consulter, écriture pour modifier, gestion pour supprimer ;
  sinon 403). Les paramètres de l'instance (entreprise, utilisateurs, rôles, modules) sont réservés aux administrateurs.
- Moteur de données : seuls les champs déclarés sont lus, écrits, triés ou filtrés ; toute valeur venue de l'utilisateur
  passe en paramètre SQL ; les champs sensibles (salaires…) ne sortent qu'au niveau gestion.
- Sessions : jeton aléatoire dans un cookie `HttpOnly`, `SameSite=Lax`, `Secure` en HTTPS. La base n'en garde que
  l'empreinte SHA-256. Les sessions sont révoquées au changement de mot de passe ou à la désactivation du compte.
- CSRF : une requête d'écriture portant un en-tête `Origin` étranger est refusée.
- En-têtes : CSP stricte sur l'interface, `nosniff`, `Referrer-Policy`, `X-Frame-Options`.
- Chiffrement des montants, fournisseurs, catégories et résumés des documents. La clé est dans `data/.encryption_key`
  ou dans `CAFFEIN_ENCRYPTION_KEY`.
- Fichiers : les chemins sont vérifiés contre la traversée de répertoire, les uploads sont limités à 20 Mo et les archives
  de restauration sont validées.

### Modèle de données

Socle : `profile` (l'entreprise, une seule ligne) · `users` (rôle administrateur ou membre, `role_id`) · `sessions`
· `roles`, `role_permissions`, `user_permissions` (droits par module) · `modules` (activation) · `schema_migrations`
(versions des modules) · `notifications` · `emails` · `job_runs` · `dashboard_views`.

Ventes et comptabilité (tables historiques) : `clients` · `invoices` (factures **et** devis, champ `kind`) et leurs lignes
`invoice_lines` · `documents` (justificatifs classés, champs chiffrés) · `declarations` · `alerts_sent`.

Modules : des tables préfixées par la clé du module (`technical_articles`, `stock_movements`, `hr_employees`…), créées par
les migrations du module. Pas de clé étrangère d'un module vers un autre : la référence est vérifiée par le moteur.

**Faire évoluer le schéma** : pour le socle, ajoutez une entrée à la fin de `MIGRATIONS` dans `db.py` ; pour un module,
ajoutez une version à la liste `MIGRATIONS` du module. Ne modifiez jamais une migration déjà publiée : les instances
existantes l'ont déjà appliquée.

## Scripts d'automatisation (`jobs/`)

Chaque script est une fonction décorée :

```python
@job("mon_script", title="…", description="…", replaces="…", schedule=daily("07:30"))
def run() -> dict:
    ...
    return {"summary": "3 éléments traités", "notable": True}
```

- `schedule` : `every(minutes=N)`, `daily("HH:MM")` (fuseau `CAFFEIN_TIMEZONE`) ou `on_event("…")` (déclenché par le code).
- Valeur de retour : `summary` (affiché dans l'interface), `status` (`success` par défaut, `warning` ou `error`),
  `notable` (affiché dans « Ce que Caffein a fait pour vous »), `quiet` (exécution planifiée sans rien à faire : non journalisée).
- Importez le module à la fin de `jobs/__init__.py` et ajoutez son nom dans `DISPLAY_ORDER`, sa traduction (`jobs.<nom>.*`)
  dans `frontend/src/lib/i18n.js` et son icône dans `frontend/src/components/jobIcons.js`.
- Un script appartient à un module (`Module.jobs`) : il ne tourne pas quand ce module est désactivé, et n'apparaît
  qu'aux utilisateurs qui peuvent consulter le module.

| Script | Ancien workflow n8n |
|---|---|
| `process_inbox` | Factures automatiques v0.2 |
| `generate_pdf` | Génération PDF (Gotenberg) |
| `send_invoice` | Envoi email facture |
| `auto_reminders` | Relances automatiques |
| `onboarding_emails` | Onboarding |
| `newsletter_notifications` | Notifications from newsletter |
| `setup_drive` | First Connection v2 |
| `fiscal_alerts` | *(nouveau)* |

## Interface (`frontend/src/`)

- `App.jsx` : routes (`/login`, `/setup`, `/f/:jeton` publiques ; `/` et `/:module/:page` sous `ProtectedRoute` ;
  anciennes adresses redirigées).
- `components/AppLayout.jsx`, `components/layout/` : barre latérale des modules, barre du haut et onglets des pages,
  construits depuis `/api/meta` (`context/MetaContext.jsx`).
- `components/entity/` : écrans générés pour les entités (liste avec recherche, filtres, tri, export ; fiche avec lignes,
  actions et totaux recalculés par le serveur pendant la saisie).
- `modules/<clé>/` : écrans sur mesure d'un module (factures, TVA, paramètres…), déclarés dans `modules/index.js`.
- `context/` : `AuthContext` (session, installation, mode démo), `AppContext` (profil, configuration), `MetaContext`,
  thème, langue, notifications toast.
- `lib/i18n.js` : les chaînes de l'interface, en `[français, anglais]` ; les libellés des modules et des champs viennent
  du serveur, déjà dans les deux langues. Les documents légaux (PDF, emails) restent en français.
- `lib/api.js` : client HTTP. Une réponse 401 renvoie vers la connexion.
- Styles : `index.css` (variables de thème `:root` / `[data-theme='sombre']`), sans framework CSS.
- Polices embarquées (`@fontsource`), aucune ressource externe : compatible avec la CSP et le RGPD.

## Tests

`backend/tests/` (pytest) couvre les calculs fiscaux, le chiffrement, l'analyse hors-ligne, le cycle de vie des factures,
les scripts, l'API, l'authentification, la protection CSRF, l'assistant d'installation et la sauvegarde/restauration ;
`test_modules.py` couvre le socle modulaire (activation, droits, moteur de données, événements, mise à jour d'une instance
existante) et `tests/modules/` chaque module.
La CI GitHub vérifie aussi le build de l'interface, l'image Docker et une installation complète avec `install.sh` sur Ubuntu.
