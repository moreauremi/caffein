#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# Commande `caffein` dans le conteneur :  docker compose exec caffein caffein backup
cd /app/backend || exit 1
exec python -m caffein "$@"
