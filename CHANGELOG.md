# Journal des modifications

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/). Versions selon [SemVer](https://semver.org/lang/fr/).

## [Non publié]

Caffein devient un **ERP modulaire** : les onglets Factures, TVA, URSSAF… laissent la place à des modules qui
s'activent et se règlent par utilisateur. Voir `docs/modules.md`.

### Ajouté
- **Modules** : Accueil, Données techniques, RH, Achats, Ventes, CRM, Production, Logistique, Projets, Qualité,
  Maintenance, Comptabilité et Paramètres. Chaque module apporte ses tables SQL, ses écrans, ses chiffres clés, ses
  raccourcis et ses données de démonstration ; il s'active ou se désactive dans Paramètres → Modules (dépendances
  vérifiées), et l'assistant d'installation propose de les choisir.
- **Droits par module** : rôles (grille module × niveau : aucun, lecture, écriture, gestion), dérogations par
  utilisateur, rôles fournis (Équipe, Lecture seule, Commercial, Acheteur, Production, RH, Comptable). Un module sans
  droit disparaît de la navigation ; le serveur répond 404 (module inactif) ou 403 (niveau insuffisant).
- **Moteur de données** : un module déclare ses entités (champs typés, lignes, actions, calculs) et Caffein en tire
  l'API (`/api/data/…` : liste, recherche, filtres, tri, fiche, actions, aperçu des calculs, export CSV) et les écrans.
  Les calculs (totaux, coûts de revient, stocks, soldes…) sont faits par le serveur, y compris pendant la saisie.
- **Événements entre modules** : livrer une commande sort le stock, réceptionner un achat l'alimente, déclarer une
  fabrication consomme les composants, si la Logistique est active. Une fiche utilisée par un autre module ne se
  supprime pas.
- **Navigation** : barre latérale des modules (repliable, en tiroir sur mobile), onglets des pages, accueil avec les
  chiffres clés de chaque module ; Paramètres en pages (compte, apparence, entreprise, fiscalité, notifications,
  utilisateurs, rôles et droits, modules, automatisations, à propos).
- **Mes vues** (Accueil → Mes vues) : un tableau de bord qui se compose en langage naturel (« mon chiffre d'affaires par mois et mes
  impayés », « ajoute mes dépenses », « enlève les impayés »). L'IA choisit des cartes dans un catalogue fermé (chiffres clés,
  CA par mois ou par client, impayés, dépenses, TVA, devis, échéances) et ne reçoit jamais les données ; sans clé, une
  analyse locale prend le relais. Les vues s'enregistrent par utilisateur et se rechargent sans IA. Lecture seule : une
  demande de modification est refusée. Les chiffres clés de tous les modules accessibles sont aussi proposés.
  Voir `docs/tableau-de-bord-ia.md`.
- **Vue « Tableau »** : les listes à statuts (commandes, absences, notes de frais, opportunités, tâches…) s'affichent
  aussi en colonnes, une par statut, avec le nombre de fiches et le total de chaque colonne calculés par le serveur.
- **Accueil** : une section « À traiter » (retards, ruptures, validations en attente), puis une carte par module.
- **Contrat des modules** (`backend/tests/test_module_contract.py`) : tout module, présent ou futur, est vérifié sans
  test à écrire — déclaration, tables, écrans sur les données de démonstration, chiffres clés sur une base vide, rôle
  « Lecture seule », et désactivation sans casser les autres modules.
- Les listes de choix ne proposent plus les fiches inactives (article arrêté, fournisseur, salarié parti).
- Migration 3 : table `dashboard_views`.

### Modifié
- Les lignes des factures et devis sont dans la table `invoice_lines` (elles étaient dans un champ JSON) ; la migration 4
  les recopie. Les totaux d'une facture en cours de saisie sont calculés par le serveur.
- Les membres reçoivent le rôle « Équipe (accès complet) » : mêmes accès qu'avant.
- Les adresses changent (`/ventes/factures`, `/comptabilite/tva`…) ; les anciennes (`/factures`, `/tva`, `/urssaf`,
  `/documents`, `/automatisations`, `/vues`) redirigent, les liens `/f/…` envoyés aux clients ne changent pas.
- Les scripts d'automatisation appartiennent à un module : ils s'arrêtent quand le module est désactivé.
- Les montants sont arrondis au centime « à la française » (la moitié vers le haut : 0,125 € → 0,13 €) au lieu de
  l'arrondi au pair de Python.

### Corrigé
- Enregistrer une fiche n'efface plus les colonnes de ses lignes invisibles pour l'utilisateur (référence vers un
  module désactivé, champ sensible) : les lignes sont mises à jour par identifiant.
- Une commande annulée peut être supprimée (la règle du module décide, même si la fiche est verrouillée).
- Une case oui/non envoyée vide garde sa valeur au lieu de faire échouer l'enregistrement.
- Deux réceptions simultanées du même document ne comptent plus deux fois le stock.
- Un ordre de fabrication terminé garde les coûts du jour de sa fin (ils ne suivent plus les prix).
- Un client utilisé par un autre module (prospect, opportunité, projet…) ne peut plus être supprimé depuis l'écran des
  factures.

### Sécurité
- Un fichier HTML ou SVG déposé dans les justificatifs n'est plus affiché depuis l'adresse de Caffein (il pouvait
  exécuter un script avec la session de la personne qui l'ouvrait) : seuls les PDF et les images s'affichent, le reste
  se télécharge, et les réponses de l'API portent une politique de sécurité (CSP) qui n'exécute rien.
- Hors du mode démo, le compte de démonstration ne s'ouvre plus, même si un visiteur lui a donné un mot de passe.
- Rembourser une note de frais, qui ajoute un justificatif de TVA déductible, demande le droit d'écriture sur la
  Comptabilité.

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
