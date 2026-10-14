# Journal des modifications

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/). Versions selon [SemVer](https://semver.org/lang/fr/).

## [Non publié]

### Ajouté
- **Mes vues** (`/vues`) : un tableau de bord qui se compose en langage naturel (« mon chiffre d'affaires par mois et mes
  impayés », « ajoute mes dépenses », « enlève les impayés »). L'IA choisit des cartes dans un catalogue fermé (chiffres clés,
  CA par mois ou par client, impayés, dépenses, TVA, devis, échéances) et ne reçoit jamais les données ; sans clé, une
  analyse locale prend le relais. Les vues s'enregistrent par utilisateur et se rechargent sans IA. Lecture seule : une
  demande de modification est refusée. Voir `docs/tableau-de-bord-ia.md`.
- Migration 3 : table `dashboard_views`.

## [2.0.0] — 2026-10-07

Première version libre et auto-hébergeable.

### Ajouté
- Installation sur un serveur Linux (`install.sh` : utilisateur dédié, service systemd durci, mises à jour avec sauvegarde
  préalable, désinstallation) et image Docker avec `docker-compose.yml`.
- Assistant d'installation au premier lancement : entreprise, régime fiscal, compte administrateur, données de démo en option.
- Comptes utilisateurs (rôles administrateur et membre), sessions sécurisées, gestion des utilisateurs, changement de mot de passe.
- Mode démonstration (`CAFFEIN_DEMO=1`) avec le bouton « Accès démo ».
- Ligne de commande d'administration : `create-admin`, `reset-password`, `users`, `backup`, `restore`, `migrate`, `health`.
- Migrations de schéma automatiques.
- Envoi des emails par SMTP, en plus de Resend et du mode simulé.
- Page « À propos » avec la licence et le lien vers le code source (`CAFFEIN_SOURCE_URL`, AGPL section 13).
- CI GitHub (tests, lint, build, image Docker, installation Linux) et publication des versions (archive et image GHCR).

### Modifié
- Les workflows n8n sont remplacés par des scripts Python planifiés dans le serveur.
- Supabase est remplacé par SQLite ; Google Drive par un dossier de classement local.
- Polices embarquées : plus aucun appel à Google Fonts.
- L'application est servie à la racine (`/`, `/factures`…). Les anciennes adresses `/app/…` sont redirigées.

### Retiré
- Landing page marketing, abonnement Stripe et faux bouton de connexion (remplacé par le mode démo).
