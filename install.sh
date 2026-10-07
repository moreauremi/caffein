#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Installe ou met à jour Caffein sur un serveur Linux avec systemd
# (Debian, Ubuntu, Fedora, RHEL/Rocky/Alma, Arch, openSUSE).
#
#   sudo ./install.sh                         installation (ou mise à jour) avec les réglages par défaut
#   sudo ./install.sh --url https://caffein.mondomaine.fr --host 127.0.0.1 --port 8000
#   sudo ./install.sh --demo                  instance de démonstration (bouton « Accès démo »)
#
# Emplacements :
#   /opt/caffein                 code + environnement Python   (remplacé à chaque mise à jour)
#   /etc/caffein/caffein.env     configuration                 (conservée)
#   /var/lib/caffein             base, documents, clé          (conservés)
#   /usr/local/bin/caffein       commande d'administration
set -euo pipefail

APP_DIR=/opt/caffein
CONF_DIR=/etc/caffein
CONF_FILE=$CONF_DIR/caffein.env
DATA_DIR=/var/lib/caffein
APP_USER=caffein
SERVICE=caffein

HOST="" PORT="" URL="" DEMO="" START=1 ASSUME_YES=0
PYTHON=${PYTHON:-python3}   # ex. : sudo PYTHON=python3.11 ./install.sh (RHEL/Rocky 8)

usage() {
  sed -n '4,17p' "$0" | sed 's/^# \{0,1\}//'
  cat <<'EOF'

Options :
  --host ADRESSE   interface d'écoute (défaut 127.0.0.1 ; 0.0.0.0 pour écouter sur le réseau)
  --port PORT      port HTTP (défaut 8000)
  --url URL        adresse publique de l'instance (liens des emails), ex. https://caffein.example.com
  --demo           active le mode démonstration
  --no-start       installe sans démarrer le service
  -y, --yes        installe les dépendances système sans demander
  -h, --help       affiche cette aide
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --host) HOST=${2:?}; shift 2 ;;
    --port) PORT=${2:?}; shift 2 ;;
    --url) URL=${2:?}; shift 2 ;;
    --demo) DEMO=1; shift ;;
    --no-start) START=0; shift ;;
    -y|--yes) ASSUME_YES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Option inconnue : $1" >&2; usage; exit 2 ;;
  esac
done

say()  { printf '\033[1;38;5;202m→\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m✓\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

confirm() {
  [ "$ASSUME_YES" = 1 ] && return 0
  read -r -p "$1 [O/n] " answer
  case "${answer:-o}" in [oOyY]*) return 0 ;; *) return 1 ;; esac
}

[ "$(id -u)" -eq 0 ] || die "Lancez ce script avec sudo : sudo $0 $*"
command -v systemctl >/dev/null 2>&1 || die "systemd est requis (utilisez sinon l'image Docker)."

SRC_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
[ -f "$SRC_DIR/backend/caffein/__init__.py" ] || die "Lancez ce script depuis le dossier du projet Caffein."
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC_DIR/backend/caffein/__init__.py")
UPDATE=0
[ -d "$APP_DIR/backend" ] && UPDATE=1

echo
if [ "$UPDATE" = 1 ]; then say "Mise à jour de Caffein vers la version $VERSION"; else say "Installation de Caffein $VERSION"; fi

# ── 1. Python ≥ 3.10 avec venv ───────────────────────────────────────────
python_ok() {
  command -v "$PYTHON" >/dev/null 2>&1 &&
    "$PYTHON" -c 'import sys, venv, ensurepip; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

if ! python_ok; then
  if command -v apt-get >/dev/null 2>&1; then PKGS="python3 python3-venv python3-pip"; INSTALL="apt-get update -q && apt-get install -y -q $PKGS"
  elif command -v dnf >/dev/null 2>&1; then PKGS="python3 python3-pip"; INSTALL="dnf install -y -q $PKGS"
  elif command -v pacman >/dev/null 2>&1; then PKGS="python python-pip"; INSTALL="pacman -S --noconfirm --needed $PKGS"
  elif command -v zypper >/dev/null 2>&1; then PKGS="python3 python3-pip"; INSTALL="zypper --non-interactive install $PKGS"
  else die "Installez Python ≥ 3.10 avec le module venv, puis relancez."; fi
  confirm "Python ≥ 3.10 (avec venv) est requis. Installer : $PKGS ?" || die "Installation annulée."
  sh -c "$INSTALL"
  python_ok || die "Python ≥ 3.10 avec venv reste introuvable. Installez une version récente (ex. python3.11)
  puis relancez avec : sudo PYTHON=python3.11 $0"
fi
ok "Python $("$PYTHON" -c 'import platform; print(platform.python_version())')"

# ── 2. Interface web (déjà buildée dans les archives de version) ─────────
if [ ! -f "$SRC_DIR/frontend/dist/index.html" ]; then
  command -v npm >/dev/null 2>&1 || die "L'interface n'est pas buildée et Node.js est absent.
  Installez Node.js ≥ 18 (https://nodejs.org) ou utilisez une archive de version qui contient frontend/dist."
  say "Build de l'interface web (npm)…"
  BUILD_USER=${SUDO_USER:-root}
  if [ "$BUILD_USER" != root ]; then
    runuser -u "$BUILD_USER" -- sh -c "cd '$SRC_DIR/frontend' && npm ci --no-audit --no-fund && npm run build"
  else
    (cd "$SRC_DIR/frontend" && npm ci --no-audit --no-fund && npm run build)
  fi
fi
ok "Interface web prête"

# ── 3. Utilisateur système ───────────────────────────────────────────────
if ! id "$APP_USER" >/dev/null 2>&1; then
  NOLOGIN=$(command -v nologin || echo /usr/sbin/nologin)
  useradd --system --user-group --home-dir "$DATA_DIR" --no-create-home --shell "$NOLOGIN" "$APP_USER"
  ok "Utilisateur système « $APP_USER » créé"
fi

# ── 4. Code de l'application ─────────────────────────────────────────────
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
(cd "$SRC_DIR" && tar --exclude='__pycache__' --exclude='.pytest_cache' --exclude='.ruff_cache' \
  -cf - backend/caffein backend/requirements.txt frontend/dist LICENSE README.md .env.example) | tar -xf - -C "$STAGE"
install -d -m 755 "$APP_DIR"
rm -rf "$APP_DIR/backend" "$APP_DIR/frontend"
cp -R "$STAGE/backend" "$STAGE/frontend" "$STAGE/LICENSE" "$STAGE/README.md" "$STAGE/.env.example" "$APP_DIR/"
chown -R root:root "$APP_DIR"
chmod -R u=rwX,go=rX "$APP_DIR"
ok "Code installé dans $APP_DIR"

# ── 5. Environnement Python ──────────────────────────────────────────────
if [ ! -x "$APP_DIR/venv/bin/python" ] || ! "$APP_DIR/venv/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  rm -rf "$APP_DIR/venv"
  "$PYTHON" -m venv "$APP_DIR/venv"
fi
say "Installation des dépendances Python…"
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/backend/requirements.txt"
ok "Dépendances Python installées"

# ── 6. Configuration et données ──────────────────────────────────────────
install -d -m 750 -o root -g "$APP_USER" "$CONF_DIR"
set_conf() {  # set_conf CLÉ VALEUR : remplace ou ajoute la ligne CLÉ=VALEUR
  local key=$1 value=$2
  if grep -qE "^#? ?${key}=" "$CONF_FILE"; then
    sed -i -E "s|^#? ?${key}=.*|${key}=${value}|" "$CONF_FILE"
  else
    printf '%s=%s\n' "$key" "$value" >> "$CONF_FILE"
  fi
}
if [ ! -f "$CONF_FILE" ]; then
  cp "$APP_DIR/.env.example" "$CONF_FILE"
  set_conf CAFFEIN_DATA_DIR "$DATA_DIR"
  set_conf CAFFEIN_HOST "${HOST:-127.0.0.1}"
  set_conf CAFFEIN_PORT "${PORT:-8000}"
  set_conf CAFFEIN_APP_URL "${URL:-http://localhost:${PORT:-8000}}"
  set_conf CAFFEIN_DEMO "${DEMO:-0}"
  ok "Configuration créée : $CONF_FILE"
else
  [ -n "$HOST" ] && set_conf CAFFEIN_HOST "$HOST"
  [ -n "$PORT" ] && set_conf CAFFEIN_PORT "$PORT"
  [ -n "$URL" ] && set_conf CAFFEIN_APP_URL "$URL"
  [ -n "$DEMO" ] && set_conf CAFFEIN_DEMO "$DEMO"
  ok "Configuration conservée : $CONF_FILE"
fi
chown root:"$APP_USER" "$CONF_FILE"
chmod 640 "$CONF_FILE"
install -d -m 750 -o "$APP_USER" -g "$APP_USER" "$DATA_DIR"

# ── 7. Commande d'administration ─────────────────────────────────────────
cat > /usr/local/bin/caffein <<EOF
#!/bin/sh
# Commande d'administration de Caffein (installée par install.sh) — ex. : sudo caffein backup
export CAFFEIN_ENV_FILE=$CONF_FILE PYTHONDONTWRITEBYTECODE=1
cd $APP_DIR/backend || exit 1
if [ "\$(id -u)" = 0 ]; then
  exec runuser -u $APP_USER -- env CAFFEIN_ENV_FILE=$CONF_FILE PYTHONDONTWRITEBYTECODE=1 $APP_DIR/venv/bin/python -m caffein "\$@"
fi
if [ "\$(id -un)" != "$APP_USER" ]; then
  echo "Utilisez sudo : sudo caffein \$*" >&2
  exit 1
fi
exec $APP_DIR/venv/bin/python -m caffein "\$@"
EOF
chmod 755 /usr/local/bin/caffein

# ── 8. Base de données et service systemd ────────────────────────────────
if [ "$UPDATE" = 1 ] && systemctl is-active --quiet "$SERVICE"; then
  say "Sauvegarde avant mise à jour…"
  /usr/local/bin/caffein backup >/dev/null && ok "Sauvegarde créée dans $DATA_DIR/backups"
fi
/usr/local/bin/caffein migrate >/dev/null
ok "Base de données à jour"

install -m 644 "$SRC_DIR/deploy/caffein.service" /etc/systemd/system/$SERVICE.service
systemctl daemon-reload
if [ "$START" = 1 ]; then
  systemctl enable --quiet "$SERVICE"
  systemctl restart "$SERVICE"
  CONF_PORT=$(sed -n 's/^CAFFEIN_PORT=//p' "$CONF_FILE" | tail -1)
  for _ in $(seq 1 30); do
    if /usr/local/bin/caffein health >/dev/null 2>&1; then break; fi
    sleep 1
  done
  /usr/local/bin/caffein health >/dev/null 2>&1 || die "Le service ne répond pas. Consultez : journalctl -u $SERVICE -n 50"
  ok "Service « $SERVICE » démarré sur le port ${CONF_PORT:-8000}"
fi

APP_URL=$(sed -n 's/^CAFFEIN_APP_URL=//p' "$CONF_FILE" | tail -1)
cat <<EOF

  Caffein $VERSION est prêt.

  Adresse         ${APP_URL:-http://localhost:8000}
  Configuration   $CONF_FILE   (puis : sudo systemctl restart $SERVICE)
  Données         $DATA_DIR
  Journaux        journalctl -u $SERVICE -f
  Sauvegarde      sudo caffein backup
  Mise à jour     récupérez la nouvelle version puis relancez : sudo ./install.sh

EOF
if [ "$UPDATE" = 0 ]; then
  echo "  Ouvrez l'adresse ci-dessus : l'assistant d'installation crée votre entreprise et le compte administrateur."
  echo "  Pour un accès depuis Internet, placez Caffein derrière un reverse proxy HTTPS (exemples dans deploy/)."
  echo
fi
