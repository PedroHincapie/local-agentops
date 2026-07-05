#!/usr/bin/env bash
# Local AgentOps — statusline hook (Claude Code).
#
# Claude Code invoca este script en cada tick y le pasa el JSON de estado por stdin.
# Responsabilidad triple:
#   1) Renderizar la statusline normal a stdout (lo que ve el usuario en su terminal).
#   2) Conservar un respaldo local del JSON crudo (spool .jsonl) por si el backend
#      está caído — así ningún tick se pierde y puede reprocesarse.
#   3) Reenviar, *fire-and-forget*, el MISMO JSON crudo a POST /api/snapshots.
#
# INVARIANTE: este script NUNCA debe bloquear el render. El reenvío va con timeout
# corto y en segundo plano; si el backend está caído o lento, la statusline no se
# congela. El hook es "tonto": no transforma el JSON, solo lo reenvía.

set -euo pipefail

AGENTOPS_URL="${AGENTOPS_URL:-http://127.0.0.1:8787/api/snapshots}"
AGENTOPS_SPOOL="${AGENTOPS_SPOOL:-$HOME/.agentops/statusline.jsonl}"

# Leer todo el stdin (el JSON crudo del statusline).
INPUT="$(cat)"

# 1) Render mínimo pero útil de la statusline. Usa jq si está disponible.
if command -v jq >/dev/null 2>&1; then
  printf '%s' "$INPUT" | jq -r '
    "◈ " + (.model.display_name // "Claude")
    + " · 5h " + ((.rate_limits.five_hour.used_percentage // "?")|tostring) + "%"
    + " · 7d " + ((.rate_limits.seven_day.used_percentage // "?")|tostring) + "%"
    + (if .cost.total_cost_usd then " · $" + (.cost.total_cost_usd|tostring|.[0:5]) else "" end)
  ' 2>/dev/null || printf 'Claude Code'
else
  printf 'Claude Code'
fi

# 2) Respaldo local (append). No bloquea el render de forma perceptible.
mkdir -p "$(dirname "$AGENTOPS_SPOOL")" 2>/dev/null || true
printf '%s\n' "$INPUT" >> "$AGENTOPS_SPOOL" 2>/dev/null || true

# 3) Reenvío no bloqueante: timeout 1s, en background, salida descartada.
#    El '&' lo desacopla del render; el subshell evita que set -e mate el render.
(
  curl -m 1 -s -o /dev/null -X POST "$AGENTOPS_URL" \
    -H 'Content-Type: application/json' \
    --data-binary "$INPUT" >/dev/null 2>&1 || true
) &

exit 0
