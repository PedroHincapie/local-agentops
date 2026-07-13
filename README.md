# Local AgentOps

> Observabilidad operativa local para **Claude Code**.

Local AgentOps es una aplicación **local-first, de un solo usuario** que observa tu uso de
Claude Code —ventanas de rate limit, tokens, contexto, costo y sesiones— y lo relaciona con
jornadas y proyectos para que sepas, en cualquier momento del día, cuánto margen operativo te
queda. Todo el procesamiento y almacenamiento es local: sin servidor central, sin telemetría
externa. Cada usuario corre su propia instancia contra sus propios datos.

> **Alcance del MVP.** Este MVP soporta **únicamente Claude Code**. No hay capa multi-provider:
> es una decisión de producto para mantener la herramienta simple. La abstracción para futuros
> providers queda "aparcada" detrás de una sola interfaz interna (`CaptureSource`), sin
> reintroducir un catálogo de providers. La visión multi-provider (Codex, Gemini CLI) es trabajo
> **futuro**, no parte del MVP.
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

- **Solo Claude Code.** Ningún catálogo de providers ni tablas `providers`/`provider_capabilities`.
- **Nunca inventar un valor.** Cada dato conserva su origen (`source_type`, `source_name`,
  `data_quality`). Si una fuente falla, la métrica degrada a "no disponible", no a una suposición.
- **La métrica operativa canónica** es `rate_limits.five_hour` / `rate_limits.seven_day` del
  statusline (coincide con la UI del plan de Anthropic). El costo en USD es **referencial** en
  planes de suscripción.
- **El hook nunca bloquea** el render del statusline (fire-and-forget).
- **Local y loopback.** La API escucha en `127.0.0.1:8787` por defecto; no se expone a la red.
- **SQLite** (archivo local, modo WAL). Toda la lógica vive en el backend.

---

## Cómo funciona

```
Claude Code → hook (statusline) → POST /api/snapshots → normalizador → SQLite
                                                              ↓
     motor de recomendaciones → API REST + WebSocket (/api/ws/dashboard) → dashboard (SPA)

              ccusage (reconciliador cada 5 min) ─────────────┘  (red de seguridad)
```

La captura es **híbrida**, con dos fuentes detrás de una única interfaz interna `CaptureSource`:

- **Hook del statusline (primaria, push).** Un script cableado en `~/.claude/settings.json`
  renderiza tu statusline normal y, *fire-and-forget*, reenvía el JSON crudo de cada tick a
  `POST /api/snapshots`. El **hook es tonto**: no transforma nada; toda la normalización vive en
  el backend. Además guarda un respaldo local en `~/.agentops/statusline.jsonl`.
- **Reconciliador ccusage (red de seguridad, pull).** Un job APScheduler cada 5 minutos invoca
  `ccusage` (`ccusage blocks --active --json`) para recuperar uso ocurrido mientras el backend
  estuvo caído y recomputar agregados. Es **reconciliación, no** captura primaria; sus snapshots
  no degradan el estado en vivo (no traen `rate_limits`).

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

`source_type` clasifica la procedencia; `source_name` es la fuente concreta (`statusline` /
`ccusage` / `manual`); `data_quality` expresa confianza/completitud/frescura. Una métrica ausente
es `null`, no `0`, y las agregaciones no mezclan bases contables incompatibles.

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
guarda su `reason` (p. ej. "Ventana de 5h al 45%, 7d al 7%."). Tipos previstos: `continue`,
`reduce_context`, `split_task`, `new_session`, `reserve_for_critical`, `review_project`, `pause`.
Severidades: `info`, `warning`, `critical`.

---

## API local

Prefijo `/api`, base `http://localhost:8787`, JSON, timestamps ISO-8601 en UTC. El contrato
completo (shapes de request/response) está en [`docs/API_CONTRACT.md`](docs/API_CONTRACT.md).

| Método y ruta | Propósito |
|---|---|
| `POST /api/snapshots` | Ingesta del hook (crudo). Idempotente, no bloqueante, deduplicada. |
| `GET /api/dashboard` | Vista consolidada que consume el SPA (estado, ventanas, sesión, costo, recomendaciones). |
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
- **`usage_snapshots`** — tabla núcleo. Cada tick normalizado: clasificación de origen
  (`source_type`/`source_name`/`data_quality`), `content_hash` para dedup, identidad de
  sesión/workspace, modelo/CLI, costo/actividad, contexto/tokens y las cuatro columnas oficiales
  de `rate_limits` (5h/7d, porcentaje y `resets_at`).
- **`recommendations`** — recomendación operativa (`recommendation_type`, `severity`, `message`,
  `reason`, `acknowledged_at`). "Activa" = `acknowledged_at is null`.
- **`usage_events`** — eventos operativos (fallos de captura, cambios de estado). *Pendiente en
  hitos posteriores.*

> Las tablas `providers` / `provider_capabilities` de la visión multi-provider **no** forman parte
> del MVP.

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

**Fase 4+ — Multi-provider (futuro, fuera del MVP).** Nuevas fuentes (Codex, Gemini CLI) detrás de
`CaptureSource`, comparando solo dimensiones realmente equivalentes. Añadir una fuente no debe
tocar el dashboard.

---

**Estado:** MVP implementado y corriendo en `main` (Hitos 0–4 + endpoints del contrato §4; 43
tests en verde). Captura en vivo vía hook + reconciliador `ccusage`, push por WebSocket
(`/api/ws/dashboard`) y SPA servido en el mismo origen desde `frontend/public/`.
