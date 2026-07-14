# Local AgentOps

> Observabilidad operativa local **multi-provider** para tus agentes de código
> (**Claude Code · Codex · Gemini**).

Local AgentOps es una aplicación **local-first, de un solo usuario** que observa tu uso de los
agentes de código —ventanas de rate limit, tokens, contexto, costo y sesiones— y lo relaciona con
jornadas y proyectos para que sepas, en cualquier momento del día, **cuánto margen operativo te
queda en cada cuenta** y puedas mover el trabajo al proveedor que tenga capacidad. Todo el
procesamiento y almacenamiento es local: sin servidor central, sin telemetría externa. Cada
usuario corre su propia instancia contra sus propios datos.

> **Alcance.** Empezó soportando solo Claude Code y ahora es **multi-provider**: Claude + OpenAI
> Codex CLI (ambos en vivo) + Gemini CLI (pendiente de que habilites su telemetría local). La
> dimensión de proveedor vive como una columna (`usage_snapshots.provider`); **no** se reintroduce
> un catálogo de providers ni tablas `providers`/`provider_capabilities`. La comparación es
> **advisory** y con **métricas nativas lado a lado** (no un número unificado forzado).
>
> El **contrato REST autoritativo** está en [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md) y la
> guía de instalación en [`docs/INSTALL.md`](docs/INSTALL.md). Cuando este README y el contrato
> difieran en detalles de endpoints o esquema, **manda el contrato**.

---

## Problema que resuelve

El uso diario de Claude Code en varios repositorios fragmenta la información necesaria para
administrar una jornada:

- No existe una vista local centralizada del estado inicial y actual del día.
- Es difícil atribuir consumo a un proyecto, sesión, modelo o tipo de tarea.
- Un dato capturado o estimado puede confundirse con una cifra oficial.
- Las decisiones operativas suelen tomarse tarde, cuando aparece un rate limit o una sesión ya
  acumuló demasiado contexto.

Local AgentOps unifica esas señales **sin ocultar su incertidumbre**. Cuando no hay una métrica
exacta, muestra la medida operativa disponible o una estimación local claramente identificada —
nunca inventa un valor.

## Principios (invariantes)

- **Multi-provider sin capa de providers.** El proveedor es solo la columna
  `usage_snapshots.provider` (`claude`|`codex`|`gemini`); ningún catálogo ni tablas
  `providers`/`provider_capabilities`. Codex/Gemini se capturan **sin sesión** (snapshots
  tagueados por proveedor). Comparación **advisory** con métricas nativas lado a lado.
- **Nunca inventar un valor.** Cada dato conserva su origen (`provider`, `source_type`,
  `source_name`, `data_quality`). Si una fuente falla, la métrica degrada a "no disponible", no a
  una suposición (p. ej. `rate_limits` de Codex a veces viene `null`).
- **La métrica operativa canónica** es `rate_limits.five_hour` / `rate_limits.seven_day` del
  statusline (coincide con la UI del plan de Anthropic). El costo en USD es **referencial** en
  planes de suscripción.
- **El hook nunca bloquea** el render del statusline (fire-and-forget).
- **Local y loopback.** La API escucha en `127.0.0.1:8787` por defecto; no se expone a la red.
- **SQLite** (archivo local, modo WAL). Toda la lógica vive en el backend.

---

## Cómo funciona

```
Claude statusline → hook → POST /api/snapshots → normalizador → SQLite
Codex / Gemini → fuente pull (reconciliador) ───────────────→  SQLite
                                                                  ↓
      motor de recomendaciones → API REST + WebSocket (/api/ws/dashboard) → dashboard (SPA)
```

Cada proveedor se captura detrás de la misma interfaz interna `CaptureSource`; el reconciliador
(`reconcile_all`, cada 5 min) recorre las fuentes habilitadas:

- **Claude — hook del statusline (primaria, push)** + **`ccusage` (red de seguridad, pull).** El
  script cableado en `~/.claude/settings.json` reenvía *fire-and-forget* el JSON crudo de cada tick
  a `POST /api/snapshots` (el **hook es tonto**; la normalización vive en el backend). `ccusage`
  recupera uso ocurrido mientras el backend estuvo caído.
- **Codex — parser de rollouts (pull).** Lee el `rollout-*.jsonl` más reciente de
  `~/.codex/sessions` y toma el último `rate_limits` (mapea `primary`/`secondary` a 5h/7d por
  `window_minutes`) + tokens. Solo lee líneas de uso/límites, nunca la conversación. Tolera
  `rate_limits: null`. Se activa con `AGENTOPS_CODEX_ENABLED=true`.
- **Gemini — OpenTelemetry local (pull, pendiente).** Parsea `~/.gemini/telemetry.log`; el margen
  es **estimado** contra la cuota RPD/TPM de tu tier. Requiere habilitar la telemetría local.

**Proveedor activo y recomendado.** El top-level del dashboard describe el **proveedor activo** (el
del último snapshot primario); `providers[]` lleva las métricas nativas de cada uno y
`recommended_provider` señala el de más margen. Cuando el activo tiene poco margen y otro tiene
más, se genera la recomendación **advisory** `switch_provider` (nombra el proveedor, no enruta).

Todo corre como **un único proceso** FastAPI/Uvicorn que sirve la API, empuja el estado del
dashboard por WebSocket (`/api/ws/dashboard`) y sirve el SPA estático del repo
(`frontend/public/`) en el mismo origen.

**Push en tiempo real.** Un `ConnectionManager` mantiene las conexiones del dashboard; tras cada
mutación relevante los routers hacen `broadcast()` del estado fresco, y al conectar el cliente
recibe el payload inicial (la misma forma que `GET /api/dashboard`). El WebSocket es una
optimización de push: la fuente de verdad sigue siendo la API REST, no un contrato aparte.

### Auto-detección

El usuario casi no configura nada: las jornadas y sesiones se **detectan solas**.

- El **primer snapshot del día** abre una jornada (`workday`); al abrir la de hoy se cierran las
  de días previos.
- Un **`session_id` nuevo** de Claude Code abre una sesión, ligada al proyecto por su ruta
  (`workspace.project_dir`). El `git_branch` se deriva localmente (`git rev-parse`), no viene en
  el statusline.
- Lo **único manual** es, opcionalmente, el `objective` y el `task_type` de una sesión
  (`PATCH /api/sessions/{id}`).

---

## Tipos de datos: oficial, capturado, estimado y manual

Cada métrica conserva su procedencia. Es el corazón de "no mentir con los datos".

| Tipo | Definición | Ejemplo en el MVP |
|---|---|---|
| **`official`** | Valor canónico de Claude Code. | `rate_limits.five_hour` / `seven_day`. |
| **`captured`** | Leído de una fuente local soportada. | Tokens, contexto, costo (statusline); bloque activo (ccusage). |
| **`estimated`** | Calculado localmente. | `burn_rate` (USD/hora), proyecciones. |
| **`manual`** | Ingresado por el usuario. | `objective`, `task_type` de la sesión. |

`provider` es la cuenta (`claude`/`codex`/`gemini`); `source_type` clasifica la procedencia;
`source_name` es el mecanismo concreto (`statusline` / `ccusage` / `codex_rollout` / `gemini_otel`
/ `manual`); `data_quality` expresa confianza/completitud/frescura. Una métrica ausente es `null`,
no `0`, y las agregaciones no mezclan bases contables incompatibles.

## Estado operativo

`status` se deriva del **mayor** porcentaje entre las dos ventanas oficiales:

```
peak = max(rate_limit_5h_percentage, rate_limit_7d_percentage)

peak <  50  → verde       (uso bajo o normal)
peak <  80  → amarillo     (reducir contexto, dividir tareas, vigilar)
peak <  95  → rojo         (reservar Claude para tareas críticas)
peak >= 95  → crítico      (pausar o continuar manualmente)
sin datos de rate_limits → crítico  (nunca se inventa)
```

Umbrales configurables por `.env`. Requiere **Claude Code v1.2.80+** para `rate_limits`; en
versiones anteriores las ventanas degradan a "no disponible".

## Motor de recomendaciones

Reglas deterministas y explicables sobre el estado y las ventanas. Genera una recomendación nueva
solo cuando el estado **cambia** (no repite); la anterior queda superseded. Cada recomendación
guarda su `reason` (p. ej. "Ventana de 5h al 45%, 7d al 7%."). Tipos: `continue`, `reduce_context`,
`split_task`, `new_session`, `reserve_for_critical`, `review_project`, `pause` y `switch_provider`.
Severidades: `info`, `warning`, `critical`.

**`switch_provider`** es un flujo **independiente** del de estado (ambos pueden estar activos): se
dispara cuando el proveedor activo no está en verde y otro tiene claramente más margen, y sugiere
—advisory— cambiar a ese proveedor.

---

## API local

Prefijo `/api`, base `http://localhost:8787`, JSON, timestamps ISO-8601 en UTC. El contrato
completo (shapes de request/response) está en [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md).

| Método y ruta | Propósito |
|---|---|
| `POST /api/snapshots` | Ingesta del hook (crudo). Idempotente, no bloqueante, deduplicada. |
| `GET /api/dashboard` | Vista consolidada que consume el SPA (estado, ventanas, sesión, costo, recomendaciones, y multi-provider: `providers[]` + `active_provider` + `recommended_provider`). |
| `GET /api/sessions/current` | Sesión activa y su último snapshot. |
| `PATCH /api/sessions/{id}` | Anota las métricas manuales (`objective`, `task_type`). |
| `GET /api/usage/today` | Agregados de la jornada actual. |
| `GET /api/usage/history` | Histórico con granularidad `day`/`week`/`month` y filtros. |
| `GET /api/recommendations` | Recomendaciones activas. |
| `POST /api/recommendations/{id}/ack` | Marca una recomendación como vista. |
| `GET /api/health` | Salud del backend, fuentes y scheduler. |
| `GET /api/ping` | Sonda de vida (liveness). |
| `WS /api/ws/dashboard` | Canal de push; payload = forma de `GET /api/dashboard`. |

---

## Modelo de datos

SQLite (WAL), ids UUID, fechas en UTC. Tablas del MVP:

- **`workdays`** — jornada diaria auto-detectada (`date` única, `status` active/closed/interrupted,
  `initial_state`/`current_state`).
- **`projects`** — proyecto auto-detectado desde `workspace.project_dir` (`name` = basename,
  `repository_path` único).
- **`agent_sessions`** — sesión por `session_external_id` (`session_id` de Claude Code), ligada a
  jornada y proyecto; `model`, `git_branch` (derivado), `task_type`/`objective` (manuales).
- **`usage_snapshots`** — tabla núcleo. Cada tick normalizado: **`provider`** (`claude`/`codex`/
  `gemini`) + clasificación de origen (`source_type`/`source_name`/`data_quality`), `content_hash`
  para dedup, identidad de sesión/workspace, modelo/CLI, costo/actividad, contexto/tokens y las
  cuatro columnas oficiales de `rate_limits` (5h/7d, porcentaje y `resets_at`).
- **`recommendations`** — recomendación operativa (`recommendation_type`, `severity`, `message`,
  `reason`, `acknowledged_at`). "Activa" = `acknowledged_at is null`.
- **`usage_events`** — eventos operativos (fallos de captura, cambios de estado). *Pendiente en
  hitos posteriores.*

> El proveedor es solo la columna `usage_snapshots.provider`; **no** hay tablas `providers` /
> `provider_capabilities` (no se reintroduce un catálogo de providers). Codex/Gemini se capturan
> **sin sesión**: persisten snapshots tagueados por proveedor sin crear `agent_sessions`.

**Deduplicación:** ticks consecutivos idénticos se descartan por hash de contenido
`(session_external_id + cost + rate_limits + context)`, para no inflar la serie temporal.

---

## Stack

- **Backend:** FastAPI + Uvicorn, SQLModel/SQLAlchemy + Pydantic sobre SQLite, APScheduler (job
  reconciliador de 5 min), `httpx`/subprocess para invocar `ccusage`. Configuración por `.env`.
- **Frontend:** SPA estática **en este repositorio** (`frontend/public/`: `index.html` +
  `support.js`, sin paso de build). Consume la API documentada y el WebSocket
  `/api/ws/dashboard`; el backend la sirve en el mismo origen (`/`) desde
  `AGENTOPS_FRONTEND_DIST` (por defecto `../frontend/public`).

## Instalación y uso

Guía completa en [`docs/INSTALL.md`](docs/INSTALL.md). Resumen:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8787
```

Luego apunta tu `~/.claude/settings.json` al hook para que capture tu uso real:

```json
{
  "statusLine": {
    "type": "command",
    "command": "bash \"/RUTA/ABSOLUTA/A/proyecto-agentOps/hook/statusline-hook.sh\""
  }
}
```

Comprobaciones: el **dashboard** en `http://127.0.0.1:8787/`, `curl -s
http://127.0.0.1:8787/api/ping`, y la documentación interactiva en `http://127.0.0.1:8787/docs`.

### Desarrollo

```bash
cd backend
python -m pytest -q      # tests
ruff check app tests     # lint
mypy app                 # tipos
```

---

## Limitaciones conocidas

- **`rate_limits` requiere Claude Code v1.2.80+.** En versiones anteriores, las ventanas 5h/7d no
  están disponibles y el estado degrada explícitamente (no se inventa).
- **El costo en USD es referencial** en planes de suscripción; la métrica operativa real son los
  porcentajes de `rate_limits`.
- **`cost_today` puede subcontar** si el backend estuvo caído toda la mañana: statusline (costo
  acumulado por sesión) y ccusage (total del bloque de 5h) tienen **bases contables distintas** y
  no se suman entre sí. El reconciliador recupera actividad, pero no unifica ambas bases.
- **Atribución por sesión** puede ser parcial si varias sesiones corren en paralelo.
- **Cambios de formato del statusline o de ccusage** pueden romper el parser; por eso la
  normalización está aislada y versionada, y las fuentes viven detrás de `CaptureSource`.
- El sistema **no** hace scraping inseguro, no intercepta credenciales y marca siempre
  procedencia, confianza y frescura.

## Roadmap

**Fase 1 — MVP Claude Code (actual).** Hook del statusline, ingesta idempotente, auto-detección de
jornada/sesión/proyecto, dashboard diario, costo y burn rate, reconciliador ccusage, motor de
recomendaciones e histórico día/semana/mes.

**Fase 2 — Captura y analítica avanzadas.** `usage_events`, alertas locales, proyección de
agotamiento con intervalos de confianza, exportación CSV/JSON, reportes diarios.

**Fase 3 — Empaquetado local.** Arranque como servicio (launchd/systemd), instalador, backup y
restauración, configuración de retención y privacidad.

**Fase 4 — Multi-provider (en curso).** Columna `provider`, fuentes por proveedor detrás de
`CaptureSource`, `providers[]` + margen por cuenta en el dashboard y recomendación advisory
`switch_provider`. **Hecho:** Claude y **Codex**. **Pendiente:** **Gemini** (habilitar su
telemetría local) y afinar la agregación de costo/histórico por proveedor.

---

**Estado:** corriendo en `main`, **74 tests en verde** (CI en Python 3.11/3.13). Observabilidad
**Claude + Codex** en vivo (statusline + `ccusage` para Claude; parser de rollouts para Codex),
`providers[]` con margen por cuenta y consejo `switch_provider` en el dashboard, push por WebSocket
(`/api/ws/dashboard`) y SPA servido en el mismo origen desde `frontend/public/`. Gemini pendiente.
