# Instalación local — Local AgentOps (multi-provider: Claude · Codex · Gemini)

Guía para dejar corriendo el backend y **conectar el hook del statusline** de Claude Code
para que capture tu uso real. Todo es local, un solo usuario, sin telemetría externa.

> Arquitectura: un único proceso FastAPI en `http://127.0.0.1:8787` sirve la API REST
> y (si existe el build) el SPA estático. La captura es híbrida: **hook del statusline**
> (primaria, push) + **reconciliador ccusage** (red de seguridad, cada 5 min).

---

## 1. Requisitos

- **Python 3.11+**
- **Claude Code** — idealmente **v1.2.80+** (antes de esa versión el statusline no trae
  `rate_limits`; el resto de métricas funciona, pero el estado operativo degrada a
  "sin datos" en las ventanas 5h/7d).
- **`jq`** — lo usa el hook para renderizar la statusline y leer el JSON (`brew install jq`).
- **`ccusage`** vía `npx`/`bunx` (no requiere instalación global): el reconciliador lo
  invoca como `npx -y ccusage@latest ...`. Necesitas Node disponible.

---

## 2. Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'          # dev: pytest, ruff, mypy

cp .env.example .env             # ajusta host/puerto/umbrales si quieres
mkdir -p data                    # carpeta de la base SQLite

# Levantar el servidor (API en :8787)
uvicorn app.main:app --host 127.0.0.1 --port 8787
# En desarrollo puedes añadir --reload
```

Al arrancar, el backend:
- crea la base SQLite en `backend/data/local-agentops.db` (modo WAL, auto-creada),
- arranca el reconciliador APScheduler (cada `AGENTOPS_RECONCILE_INTERVAL_SECONDS`, 300 por defecto).

Verifica que responde:

```bash
curl -s http://127.0.0.1:8787/api/ping        # {"status":"ok"}
curl -s http://127.0.0.1:8787/api/health | jq # database ok, scheduler, fuentes
# Documentación interactiva: http://127.0.0.1:8787/docs
```

### Variables de entorno (`.env`, prefijo `AGENTOPS_`)

| Variable | Default | Qué hace |
|---|---|---|
| `AGENTOPS_HOST` / `AGENTOPS_PORT` | `127.0.0.1` / `8787` | Dónde escucha. Solo loopback por defecto. |
| `AGENTOPS_DB_URL` | `sqlite:///./data/local-agentops.db` | Ruta de la base. |
| `AGENTOPS_THRESHOLD_YELLOW/RED/CRITICAL` | `50/80/95` | Umbrales de estado sobre `peak = max(5h%, 7d%)`. |
| `AGENTOPS_RECONCILE_INTERVAL_SECONDS` | `300` | Frecuencia del reconciliador ccusage. |
| `AGENTOPS_SCHEDULER_ENABLED` | `true` | Ponlo en `false` para desactivar el reconciliador. |
| `AGENTOPS_SESSION_IDLE_MINUTES` | `120` | Cierre auto de sesión sin snapshots recientes. |
| `AGENTOPS_FRONTEND_DIST` | `../frontend/public` | El SPA del repo se sirve en `/`. |
| `AGENTOPS_CODEX_ENABLED` | `false` | Activa la captura de **Codex** (parser de rollouts). |
| `AGENTOPS_CODEX_SESSIONS_DIR` | `~/.codex/sessions` | Dónde busca los `rollout-*.jsonl`. |
| `AGENTOPS_GEMINI_ENABLED` | `false` | Activa la captura de **Gemini** (OTel local). |
| `AGENTOPS_GEMINI_TELEMETRY_LOG` | `~/.gemini/telemetry.log` | Log de telemetría local de Gemini. |
| `AGENTOPS_GEMINI_RPD` / `_TPM` | `0` / `0` | Cuota del tier para estimar el margen (`0` = desconocida). |

### Multi-provider (Codex / Gemini)

El backend observa **Claude + Codex + Gemini**. Claude va siempre (hook + `ccusage`). Para añadir
los otros:

- **Codex:** pon `AGENTOPS_CODEX_ENABLED=true`. El reconciliador leerá el `rollout-*.jsonl` más
  reciente de `~/.codex/sessions` (solo las líneas de uso/límites, nunca la conversación).
- **Gemini:** habilita la telemetría local en `~/.gemini/settings.json`
  (`{ "telemetry": { "enabled": true, "target": "local", "outfile": "~/.gemini/telemetry.log" } }`),
  úsalo un rato para que se pueble, y pon `AGENTOPS_GEMINI_ENABLED=true` (+ `RPD`/`TPM` de tu tier
  para estimar el margen).

Cada proveedor aparece como una card en el dashboard, con su margen nativo lado a lado; si el activo
se queda sin margen y otro tiene más, verás el consejo **`switch_provider`**.

---

## 3. Conectar el hook del statusline

El hook (`hook/statusline-hook.sh`) tiene **triple responsabilidad**: renderiza tu
statusline, guarda un respaldo local del tick, y reenvía el JSON crudo a
`POST /api/snapshots` en *fire-and-forget* (timeout 1s). **Nunca bloquea** el render:
si el backend está caído, tu terminal no se congela.

### 3.1 Apuntar `~/.claude/settings.json` al hook

Haz un respaldo y añade (o reemplaza) la clave `statusLine`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "bash \"/RUTA/ABSOLUTA/A/proyecto-agentOps/hook/statusline-hook.sh\""
  }
}
```

> Usa la **ruta absoluta** al hook dentro de tu checkout. El cambio afecta a **todas**
> tus sesiones de Claude Code (todas comparten esta config global).

### 3.2 Verificar el hook

El hook renderiza algo como:

```
◈ Opus 4.8 · 5h 15% · 7d 2% · $2.17
```

Prueba pasándole un tick por stdin (o simplemente abre una sesión de Claude Code):

```bash
# Con un tick guardado de ejemplo
tail -1 ~/.agentops/statusline.jsonl | bash hook/statusline-hook.sh
# Luego confirma que el snapshot llegó:
curl -s http://127.0.0.1:8787/api/dashboard | jq '{status, metrics: .metrics.five_hour}'
```

### 3.3 Respaldo local (spool)

Cada tick se anexa a `~/.agentops/statusline.jsonl` (configurable con `AGENTOPS_SPOOL`).
Es un respaldo pasivo: si el backend estuvo caído, esos ticks quedan en disco. Puedes
reprocesarlos manualmente reenviándolos:

```bash
while read -r line; do
  printf '%s' "$line" | curl -s -m 2 -X POST http://127.0.0.1:8787/api/snapshots \
    -H 'Content-Type: application/json' --data-binary @- >/dev/null
done < ~/.agentops/statusline.jsonl
```

(El backend deduplica ticks idénticos por hash de contenido, así que reenviar es seguro.)

---

## 4. Variables opcionales del hook

| Variable | Default | Qué hace |
|---|---|---|
| `AGENTOPS_URL` | `http://127.0.0.1:8787/api/snapshots` | Endpoint de ingesta. |
| `AGENTOPS_SPOOL` | `$HOME/.agentops/statusline.jsonl` | Archivo de respaldo local. |

---

## 5. Problemas comunes

- **El dashboard queda en `critical` / sin ventanas:** tu Claude Code no emite
  `rate_limits` (versión < 1.2.80) o el tick no trae esas claves. El resto de métricas
  (costo, tokens, contexto) sigue funcionando.
- **`ping` no responde:** el backend no está corriendo. El hook no falla por eso (es
  fire-and-forget), pero no se captura nada hasta levantarlo. Ver §6.
- **El dashboard muestra un día viejo:** ya no debería ocurrir — al abrir la jornada de
  hoy se cierran las de días previos. Si vienes de datos heredados, borra la base (§2).

---

## 6. (Opcional) Backend siempre arriba — LaunchAgent macOS

Para que la captura funcione día a día sin arrancar el servidor a mano, hay un
**LaunchAgent** (`RunAtLoad` + `KeepAlive`: arranca al iniciar sesión y se reinicia si
se cae). Es un servicio **persistente**, así que lo instalas tú explícitamente:

```bash
# Requiere haber creado el venv (§2). Instala y arranca:
deploy/launchd/install.sh

# Para detenerlo y desinstalarlo:
deploy/launchd/install.sh uninstall
```

El script genera el plist real desde `deploy/launchd/*.template` (sustituye rutas) en
`~/Library/LaunchAgents/com.localagentops.backend.plist` y lo carga con `launchctl`.
Los logs quedan en `~/Library/Logs/local-agentops.log`.

> Antes de instalarlo, asegúrate de **no** tener otro `uvicorn` ocupando el `:8787`
> (`lsof -ti tcp:8787 | xargs kill`).

Comprobar estado:

```bash
launchctl print gui/$(id -u)/com.localagentops.backend | grep -i state
curl -s http://127.0.0.1:8787/api/ping
```
