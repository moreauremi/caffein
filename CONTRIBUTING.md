# Contribuer à Caffein

Merci de votre intérêt ! Tickets, corrections, traductions et nouvelles fonctionnalités sont bienvenus.

## Avant de commencer

- **Un bug ?** Ouvrez un ticket avec les étapes pour le reproduire, votre type d'installation et la version
  (Paramètres → À propos).
- **Une nouvelle fonctionnalité ?** Ouvrez d'abord un ticket pour en discuter : cela évite de travailler sur une pull request
  qui ne pourrait pas être intégrée.
- **Un nouveau module ?** Suivez le guide pas à pas [docs/ajouter-un-module.md](docs/ajouter-un-module.md).
- **Une faille de sécurité ?** Pas de ticket public : suivez [SECURITY.md](SECURITY.md).

## Environnement de développement

Prérequis : Python ≥ 3.10, Node.js ≥ 18.

```bash
./start.sh --demo     # installe les dépendances, builde l'interface et lance une instance de démo
./dev.sh --demo       # ensuite, pour développer : API rechargée à chaud (:8000) + Vite (:5173)
```

Ouvrez http://localhost:5173 pendant le développement : Vite redirige `/api` vers le serveur Python.

## Vérifications avant une pull request

```bash
cd backend && .venv.nosync/bin/ruff check caffein tests && .venv.nosync/bin/python -m pytest -q
cd frontend && npm run lint && npm run build
shellcheck install.sh start.sh dev.sh deploy/*.sh      # si vous touchez aux scripts
```

La CI GitHub lance les mêmes vérifications, puis construit l'image Docker et teste une installation complète sur Ubuntu.

## Conventions

- **Langue** : code et identifiants en anglais, commentaires et documentation en français, comme le reste du projet.
- **Textes de l'interface** : jamais en dur. Ajoutez une clé dans `frontend/src/lib/i18n.js` avec la traduction française
  **et** anglaise.
- **Base de données** : toute évolution du schéma passe par une nouvelle entrée à la fin de `MIGRATIONS` (`backend/caffein/db.py`).
  On ne modifie jamais une migration publiée.
- **Fiscalité** : les taux et seuils sont dans `backend/caffein/fiscal.py`. Citez votre source officielle (urssaf.fr,
  impots.gouv.fr, Légifrance) dans la pull request.
- **Scripts d'automatisation** : un fichier par script dans `backend/caffein/jobs/` (voir [docs/architecture.md](docs/architecture.md)).
  Un script ne doit jamais faire planter le planificateur : il renvoie `status: "error"` avec un résumé lisible.
- **Sécurité** : toute nouvelle route API va dans le routeur `api` (connecté) ou `admin`, jamais `public`, sauf si elle
  doit vraiment être accessible sans compte.
- **En-tête de licence** : chaque nouveau fichier source commence par `SPDX-License-Identifier: AGPL-3.0-or-later`.
- **Tests** : toute correction de bug s'accompagne d'un test qui échouait avant.

## Pull requests

1. Créez une branche depuis `main` (`fix/…`, `feat/…`, `docs/…`).
2. Gardez la pull request centrée sur un seul sujet et décrivez le problème résolu.
3. Mettez à jour `CHANGELOG.md` (section « Non publié ») si le changement est visible pour les utilisateurs.

## Licence des contributions

Caffein est sous licence [AGPL-3.0-or-later](LICENSE). En proposant une contribution, vous acceptez qu'elle soit publiée
sous cette même licence. Aucun accord de cession (CLA) n'est demandé.
