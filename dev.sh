#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
# Développement : API Python avec rechargement auto (:8000) + Vite avec HMR (:5173, à ouvrir).
#   ./dev.sh          ./dev.sh --demo
set -euo pipefail
cd "$(dirname "$0")"
[ -x backend/.venv.nosync/bin/python ] || { echo "Lancez d'abord ./start.sh une fois pour installer les dépendances."; exit 1; }
[ -f .env ] || cp .env.example .env
[ "${1:-}" = "--demo" ] && export CAFFEIN_DEMO=1

(cd backend && .venv.nosync/bin/python -m caffein serve --reload) &
API_PID=$!
trap 'kill $API_PID 2>/dev/null' EXIT INT TERM
cd frontend && npm run dev
