#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Désinstalle Caffein.
#   sudo ./deploy/uninstall.sh           retire le service et le code, CONSERVE configuration et données
#   sudo ./deploy/uninstall.sh --purge   supprime aussi /etc/caffein, /var/lib/caffein et l'utilisateur système
set -euo pipefail

PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1
[ "$(id -u)" -eq 0 ] || { echo "Lancez ce script avec sudo." >&2; exit 1; }

if [ "$PURGE" = 1 ]; then
  read -r -p "Supprimer DÉFINITIVEMENT les données (/var/lib/caffein) ? Tapez « supprimer » : " answer
  [ "$answer" = "supprimer" ] || { echo "Annulé."; exit 1; }
fi

systemctl disable --now caffein 2>/dev/null || true
rm -f /etc/systemd/system/caffein.service /usr/local/bin/caffein
systemctl daemon-reload
rm -rf /opt/caffein
echo "✓ Service et code supprimés."

if [ "$PURGE" = 1 ]; then
  rm -rf /etc/caffein /var/lib/caffein
  userdel caffein 2>/dev/null || true
  echo "✓ Configuration, données et utilisateur supprimés."
else
  echo "  Conservés : /etc/caffein (configuration) et /var/lib/caffein (données et sauvegardes)."
fi
