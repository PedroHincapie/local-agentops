#!/usr/bin/env bash
# Local AgentOps — instala/recarga el LaunchAgent de macOS que mantiene el backend
# siempre arriba en http://127.0.0.1:8787 (RunAtLoad + KeepAlive).
#
# Uso:
#   deploy/launchd/install.sh            # instala y arranca
#   deploy/launchd/install.sh uninstall  # detiene y desinstala
#
# Requisitos previos: haber creado el venv del backend (backend/.venv) e instalado
# las dependencias — ver docs/INSTALL.md §2.

set -euo pipefail

LABEL="com.localagentops.backend"
# Raíz del repo = dos niveles arriba de este script (deploy/launchd/ -> repo/).
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEMPLATE="$PROJECT_DIR/deploy/launchd/${LABEL}.plist.template"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
DOMAIN="gui/$(id -u)"

uninstall() {
  echo "Desinstalando $LABEL ..."
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Listo. El backend ya no arranca automáticamente."
}

if [ "${1:-}" = "uninstall" ]; then
  uninstall
  exit 0
fi

# --- Validaciones ---
if [ ! -x "$PROJECT_DIR/backend/.venv/bin/uvicorn" ]; then
  echo "ERROR: no existe backend/.venv/bin/uvicorn. Crea el venv primero (docs/INSTALL.md §2)." >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"

# --- Generar el plist desde el template ---
sed -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
    -e "s|__HOME__|$HOME|g" \
    "$TEMPLATE" > "$PLIST"
echo "Escrito: $PLIST"

# --- (Re)cargar el servicio ---
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl enable "$DOMAIN/$LABEL"
echo "Cargado. Esperando a que responda en :8787 ..."

for _ in $(seq 1 20); do
  if [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8787/api/ping 2>/dev/null)" = "200" ]; then
    echo "OK — backend arriba (http://127.0.0.1:8787). Logs: ~/Library/Logs/local-agentops.log"
    exit 0
  fi
  sleep 0.5
done

echo "AVISO: no respondió a tiempo. Revisa ~/Library/Logs/local-agentops.log" >&2
exit 1
