# Architecture de Caffein

Ce document s'adresse aux personnes qui veulent comprendre ou modifier le code.

## Vue d'ensemble

```
Navigateur ──HTTP──▶ FastAPI (backend/caffein/api/main.py)
                       ├─ /api/*            routes publiques, connectées, administrateur
                       ├─ /*                interface React buildée (frontend/dist)
                       └─ planificateur     thread qui lance les scripts (jobs/)
                     SQLite (data/caffein.db) · documents (data/drive/) · boîte d'envoi (data/outbox/)
Services optionnels : Claude (IA), SMTP ou Resend (emails), IMAP (newsletters)
```

Un seul processus, une seule base. Le planificateur tourne dans le serveur : ne lancez pas plusieurs workers uvicorn.

## Backend (`backend/caffein/`)

| Module | Rôle |
|---|---|
| `config.py` | variables d'environnement, chemins, constantes |
| `db.py` | connexion SQLite et **migrations** (`MIGRATIONS`, `PRAGMA user_version`) |
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

- Trois routeurs dans `api/main.py` : `public` (santé, installation, connexion, page publique d'une facture),
  `api` (utilisateur connecté), `admin` (rôle administrateur).
- Sessions : jeton aléatoire dans un cookie `HttpOnly`, `SameSite=Lax`, `Secure` en HTTPS. La base n'en garde que
  l'empreinte SHA-256. Les sessions sont révoquées au changement de mot de passe ou à la désactivation du compte.
- CSRF : une requête d'écriture portant un en-tête `Origin` étranger est refusée.
- En-têtes : CSP stricte sur l'interface, `nosniff`, `Referrer-Policy`, `X-Frame-Options`.
- Chiffrement des montants, fournisseurs, catégories et résumés des documents. La clé est dans `data/.encryption_key`
  ou dans `CAFFEIN_ENCRYPTION_KEY`.
- Fichiers : les chemins sont vérifiés contre la traversée de répertoire, les uploads sont limités à 20 Mo et les archives
  de restauration sont validées.

### Modèle de données

`profile` (l'entreprise, une seule ligne) · `users` · `sessions` · `clients` · `invoices` (factures **et** devis, champ `kind`)
· `documents` (justificatifs classés, champs chiffrés) · `notifications` (actualités) · `emails` (journal de tous les envois)
· `job_runs` (historique des scripts) · `declarations` (périodes URSSAF déclarées) · `alerts_sent`
· `dashboard_views` (vues enregistrées de « Mes vues », propres à chaque utilisateur).

**Ajouter une colonne ou une table** : ajoutez une entrée `(3, "ALTER TABLE …")` à la fin de `MIGRATIONS` dans `db.py`.
Ne modifiez jamais une migration déjà publiée, les instances existantes l'ont déjà appliquée.

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

- `App.jsx` : routes (`/login`, `/setup`, `/f/:jeton` publiques, le reste sous `ProtectedRoute`).
- `context/` : `AuthContext` (session, installation, mode démo), `AppContext` (profil, configuration, paramètres),
  thème, langue, notifications toast.
- `lib/i18n.js` : **toutes** les chaînes, en `[français, anglais]`. `singulier|pluriel` est choisi selon `{n}`.
  Les documents légaux (PDF, emails) restent en français.
- `lib/api.js` : client HTTP. Une réponse 401 renvoie vers la connexion.
- Styles : `index.css` (variables de thème `:root` / `[data-theme='sombre']`), sans framework CSS.
- Polices embarquées (`@fontsource`), aucune ressource externe : compatible avec la CSP et le RGPD.

## Tests

`backend/tests/` (pytest) couvre les calculs fiscaux, le chiffrement, l'analyse hors-ligne, le cycle de vie des factures,
les scripts, l'API, l'authentification, les rôles, la protection CSRF, l'assistant d'installation et la sauvegarde/restauration.
La CI GitHub vérifie aussi le build de l'interface, l'image Docker et une installation complète avec `install.sh` sur Ubuntu.
