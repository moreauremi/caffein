#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Lancement local rapide (macOS, Linux, WSL) — pour un serveur, voir install.sh ou Docker.
#   ./start.sh            → http://localhost:8000 (assistant d'installation au premier lancement)
#   ./start.sh --demo     → instance de démonstration (bouton « Accès démo »)
set -euo pipefail
cd "$(dirname "$0")"

VENV=backend/.venv.nosync   # « .nosync » : ignoré par iCloud Drive
PY=${PYTHON:-python3}
ARGS=()
for arg in "$@"; do
  if [ "$arg" = "--demo" ]; then export CAFFEIN_DEMO=1; else ARGS+=("$arg"); fi
done

if [ ! -x "$VENV/bin/python" ]; then
  echo "→ Création de l'environnement Python…"
  "$PY" -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
fi
if [ ! -f "$VENV/.deps-installed" ] || [ backend/requirements.txt -nt "$VENV/.deps-installed" ]; then
  echo "→ Installation des dépendances Python…"
  "$VENV/bin/pip" install -q -r backend/requirements-dev.txt
  touch "$VENV/.deps-installed"
fi

if [ ! -d frontend/node_modules ]; then
  echo "→ Installation des dépendances de l'interface (npm)…"
  (cd frontend && npm ci --no-fund --no-audit)
fi
if [ ! -f frontend/dist/index.html ] || [ -n "$(find frontend/src frontend/index.html frontend/public -newer frontend/dist/index.html -print -quit)" ]; then
  echo "→ Build de l'interface…"
  (cd frontend && npm run build > /dev/null)
fi

[ -f .env ] || cp .env.example .env

echo "→ Caffein démarre sur http://localhost:${CAFFEIN_PORT:-8000}  (Ctrl+C pour arrêter)"
cd backend
exec .venv.nosync/bin/python -m caffein serve ${ARGS[@]+"${ARGS[@]}"}
