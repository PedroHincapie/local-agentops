#!/usr/bin/env bash
# Local AgentOps — statusline hook (Claude Code).
#
# Claude Code invoca este script en cada tick y le pasa el JSON de estado por stdin.
# Responsabilidad doble:
#   1) Renderizar la statusline normal a stdout (lo que ve el usuario en su terminal).
#   2) Reenviar, *fire-and-forget*, el MISMO JSON crudo a POST /api/snapshots.
#
# INVARIANTE: este script NUNCA debe bloquear el render. El reenvío va con timeout
# corto y en segundo plano; si el backend está caído o lento, la statusline no se
# congela. El hook es "tonto": no transforma el JSON, solo lo reenvía.

set -euo pipefail

AGENTOPS_URL="${AGENTOPS_URL:-http://127.0.0.1:8787/api/snapshots}"

# Leer todo el stdin (el JSON crudo del statusline).
INPUT="$(cat)"

# 1) Render mínimo de la statusline. Usa jq si está disponible; si no, algo neutro.
if command -v jq >/dev/null 2>&1; then
  MODEL="$(printf '%s' "$INPUT" | jq -r '.model.display_name // "Claude"' 2>/dev/null || echo "Claude")"
  PCT="$(printf '%s' "$INPUT" | jq -r '.rate_limits.five_hour.used_percentage // "?"' 2>/dev/null || echo "?")"
  printf '%s · 5h %s%%' "$MODEL" "$PCT"
else
  printf 'Claude Code'
fi

# 2) Reenvío no bloqueante: timeout 1s, en background, salida descartada.
#    El '&' lo desacopla del render; el subshell evita que set -e mate el render.
(
  curl -m 1 -s -o /dev/null -X POST "$AGENTOPS_URL" \
    -H 'Content-Type: application/json' \
    --data-binary "$INPUT" >/dev/null 2>&1 || true
) &

exit 0
