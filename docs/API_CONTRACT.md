# Local AgentOps — Contrato de la API local

> Versión 0.1 del contrato. Derivado de datos **reales** capturados del statusline de Claude Code v2.1.195.
> Este documento es el acuerdo estable entre el **backend** (FastAPI) y el **frontend** (SPA estática en `frontend/public/`, servida por el backend en el mismo origen). El contrato manda: front y back se mantienen desacoplados a través de él.

---

## 1. Convenciones generales

- **Base URL:** `http://localhost:8787`
- **Formato:** JSON (`Content-Type: application/json`).
- **Timestamps de salida:** ISO 8601 en UTC (p. ej. `2026-06-27T13:45:00Z`). Los epochs Unix que entrega Claude Code (`resets_at`) se convierten en el backend.
- **Tipos de dato (`data_quality`):** cada métrica se etiqueta según su origen.
  - `official` — valor canónico de Claude Code (`rate_limits`).
  - `captured` — leído de fuente local soportada (statusline, ccusage).
  - `estimated` — calculado localmente (burn rate, proyecciones).
  - `manual` — ingresado por el usuario (objetivo, tipo de tarea).

---

## 2. Mapeo: statusline crudo → snapshot normalizado

El **hook es tonto**: reenvía el JSON crudo del statusline tal cual a `POST /api/snapshots`. El **backend es inteligente**: normaliza, clasifica y persiste. Toda la lógica de mapeo vive en un solo lugar (el backend), nunca en el hook.

| Campo crudo (Claude Code) | Campo normalizado | data_quality |
|---|---|---|
| `session_id` | `session_external_id` | captured |
| `session_name` | `session_name` | captured |
| `transcript_path` | `transcript_path` | captured |
| `workspace.project_dir` | `project_path` | captured |
| `workspace.current_dir` | `current_dir` | captured |
| `model.id` | `model_id` | captured |
| `model.display_name` | `model_name` | captured |
| `effort.level` | `effort_level` | captured |
| `version` | `cli_version` | captured |
| `cost.total_cost_usd` | `cost_session_usd` | captured |
| `cost.total_duration_ms` | `session_duration_ms` | captured |
| `cost.total_lines_added` | `lines_added` | captured |
| `cost.total_lines_removed` | `lines_removed` | captured |
| `context_window.context_window_size` | `context_window_size` | captured |
| `context_window.used_percentage` | `context_used_percentage` | captured |
| `context_window.total_input_tokens` | `total_input_tokens` | captured |
| `context_window.total_output_tokens` | `total_output_tokens` | captured |
| `context_window.current_usage.cache_creation_input_tokens` | `cache_creation_input_tokens` | captured |
| `context_window.current_usage.cache_read_input_tokens` | `cache_read_input_tokens` | captured |
| `rate_limits.five_hour.used_percentage` | `rate_limit_5h_percentage` | **official** |
| `rate_limits.five_hour.resets_at` | `rate_limit_5h_resets_at` | **official** |
| `rate_limits.seven_day.used_percentage` | `rate_limit_7d_percentage` | **official** |
| `rate_limits.seven_day.resets_at` | `rate_limit_7d_resets_at` | **official** |

> **Notas de captura**
> - `current_usage` puede venir `null` antes de la primera llamada a la API y justo tras `/compact`. El backend tolera `null` y marca `data_quality` en consecuencia.
> - `cost_session_usd` es referencial en planes de suscripción; la métrica operativa real son los porcentajes de `rate_limits`.
> - **Deduplicación:** ticks consecutivos pueden ser idénticos. El backend calcula un hash de contenido `(session_external_id + cost + rate_limits + context)` y **descarta el snapshot si es idéntico al anterior de la misma sesión**, conservando solo `captured_at`. Esto evita inflar la serie temporal.

---

## 3. Derivación del estado operativo

`status` se deriva del **mayor** porcentaje entre las dos ventanas oficiales:

```
peak = max(rate_limit_5h_percentage, rate_limit_7d_percentage)

peak <  50  → "green"
peak <  80  → "yellow"
peak <  95  → "red"
peak >= 95  → "critical"
sin datos de rate_limits → "critical" (no se inventa)
```

Umbrales configurables vía `.env`/YAML. Con los datos del spike (`5h=45`, `7d=7`) → `peak=45` → **green**.

---

## 4. Endpoints

### 4.1 `POST /api/snapshots` — ingesta del hook

Recibe el JSON **crudo** del statusline. Idempotente, no bloqueante, tolerante a campos faltantes. El hook lo invoca en *fire-and-forget*.

**Request body:** el objeto JSON tal cual lo emite Claude Code (ver sección 2).

**Response `202 Accepted`:**
```json
{
  "accepted": true,
  "snapshot_id": "9f1c2e7a-...",
  "deduplicated": false,
  "session_external_id": "623a283b-7b38-4c89-913e-4b95e490a0c1",
  "workday_id": "2026-06-27",
  "status": "green"
}
```
Si el snapshot es idéntico al anterior: `"deduplicated": true` y `snapshot_id: null`.

---

### 4.2 `GET /api/dashboard` — vista consolidada (la que consume el front)

Es el endpoint principal del front. Devuelve todo lo necesario para pintar el dashboard en una sola llamada.

**Multi-provider.** El top-level (`status`, `metrics`, `current_session`) describe el **proveedor activo** = el del último snapshot primario entre todos (statusline→claude, codex_rollout→codex, gemini_otel→gemini). Además:
- `active_provider` — el proveedor en el que trabajas ahora (o `null` si no hay datos).
- `recommended_provider` — el proveedor con **más margen** (ranking interno 100 − max ventanas); base del consejo `switch_provider`.
- `providers[]` — una entrada por proveedor con **métricas nativas** (el front las muestra lado a lado). Ventanas ausentes → `null` (no se inventan).

**Response `200 OK`:**
```json
{
  "generated_at": "2026-06-27T13:45:12Z",
  "status": "green",
  "active_provider": "claude",
  "recommended_provider": "claude",
  "providers": [
    {
      "provider": "claude",
      "status": "green",
      "model_name": "Opus 4.8",
      "five_hour": { "used_percentage": 45, "resets_at": "2026-06-27T17:00:00Z", "resets_in_seconds": 11688, "resets_in_human": "3h 14m", "data_quality": "official" },
      "seven_day": { "used_percentage": 7, "resets_at": "2026-07-03T07:00:00Z", "resets_in_seconds": 495288, "resets_in_human": "5d 17h", "data_quality": "official" },
      "last_snapshot_at": "2026-06-27T13:45:00Z",
      "data_quality": "ok"
    },
    {
      "provider": "codex",
      "status": "yellow",
      "model_name": "gpt-5.5",
      "five_hour": null,
      "seven_day": { "used_percentage": 32, "resets_at": "2026-07-20T13:00:00Z", "resets_in_seconds": 570000, "resets_in_human": "6d 14h", "data_quality": "official" },
      "last_snapshot_at": "2026-06-27T13:40:00Z",
      "data_quality": "ok"
    }
  ],
  "workday": {
    "id": "2026-06-27",
    "date": "2026-06-27",
    "started_at": "2026-06-27T08:30:04Z",
    "status": "active",
    "initial_state": "green",
    "current_state": "green"
  },
  "current_session": {
    "id": "623a283b-7b38-4c89-913e-4b95e490a0c1",
    "session_name": "Analizar el propósito del proyecto",
    "project_name": "proyecto-agentOps",
    "project_path": "/Users/imagemaker/Documents/Proyectos/Personal/proyecto-agentOps",
    "model_name": "Opus 4.8",
    "git_branch": "main",
    "effort_level": "high",
    "task_type": null,
    "objective": null,
    "started_at": "2026-06-27T13:30:00Z"
  },
  "metrics": {
    "model_name": "Opus 4.8",
    "cost_session_usd": 0.3655365,
    "cost_today_usd": 1.842,
    "burn_rate_usd_per_hour": 0.42,
    "tokens": {
      "total_input_tokens": 32371,
      "total_output_tokens": 464,
      "cache_creation_input_tokens": 2046,
      "cache_read_input_tokens": 30323
    },
    "context": {
      "used_percentage": 3,
      "remaining_percentage": 97,
      "context_window_size": 1000000
    },
    "five_hour": {
      "used_percentage": 45,
      "resets_at": "2026-06-27T17:00:00Z",
      "resets_in_seconds": 11688,
      "resets_in_human": "3h 14m",
      "data_quality": "official"
    },
    "seven_day": {
      "used_percentage": 7,
      "resets_at": "2026-07-03T07:00:00Z",
      "resets_in_seconds": 495288,
      "resets_in_human": "5d 17h",
      "data_quality": "official"
    }
  },
  "last_snapshot_at": "2026-06-27T13:45:00Z",
  "recommendations": [
    {
      "id": "rec_01",
      "recommendation_type": "continue",
      "severity": "info",
      "message": "Uso bajo. Continúa trabajando con normalidad.",
      "reason": "Ventana de 5h al 45%, 7d al 7%."
    },
    {
      "id": "rec_02",
      "recommendation_type": "switch_provider",
      "severity": "warning",
      "message": "Te queda más margen en Codex. Considera cambiar de Claude a Codex para no depender del saldo de Claude.",
      "reason": "Claude: red (15% de margen); Codex: 95% de margen."
    }
  ]
}
```

> **Nota multi-provider.** La recomendación `switch_provider` es un flujo **independiente** del de estado (`continue`/`reduce_context`/…): ambos pueden estar activos a la vez. Es **advisory** — el sistema sugiere el proveedor con más margen, no enruta ni lanza trabajo.

---

### 4.3 `GET /api/sessions/current` — sesión activa

```json
{
  "id": "623a283b-7b38-4c89-913e-4b95e490a0c1",
  "session_name": "Analizar el propósito del proyecto",
  "project_name": "proyecto-agentOps",
  "model_name": "Opus 4.8",
  "git_branch": "main",
  "task_type": null,
  "objective": null,
  "status": "active",
  "started_at": "2026-06-27T13:30:00Z",
  "ended_at": null,
  "snapshot_count": 12,
  "cost_session_usd": 0.3655365
}
```

---

### 4.3.1 `GET /api/sessions/current/large-files` — archivos pesados del proyecto activo

Métrica auxiliar del dashboard: escanea el directorio del proyecto de la sesión activa y devuelve los **5 archivos más grandes** (`data_quality: captured`, lectura del sistema de archivos local). Excluye directorios de build/entorno y binarios comunes; ignora symlinks. Si no hay sesión activa → `404`.

**Response `200 OK`:**
```json
{
  "files": [
    { "path": "frontend/public/support.js", "size_bytes": 51200, "size_kb": 50.0 },
    { "path": "README.md", "size_bytes": 9800, "size_kb": 9.6 }
  ]
}
```
`path` es relativo al directorio del proyecto; la lista viene ordenada por tamaño descendente (máx. 5) y es `[]` si el path no existe o no es legible.

---

### 4.4 `PATCH /api/sessions/{id}` — anotar (métrica manual)

Lo único que el usuario ingresa a mano.

**Request:**
```json
{ "objective": "Documentar el ciclo de enrolamiento", "task_type": "documentación" }
```
**Response `200 OK`:** la sesión actualizada (mismo shape que 4.3).

---

### 4.5 `GET /api/usage/today` — acumulado del día

```json
{
  "workday_id": "2026-06-27",
  "status": "green",
  "cost_today_usd": 1.842,
  "peak_five_hour_percentage": 61,
  "peak_seven_day_percentage": 7,
  "totals": {
    "total_input_tokens": 184320,
    "total_output_tokens": 9210,
    "snapshots": 88,
    "sessions": 3
  },
  "by_project": [
    { "project_name": "proyecto-agentOps", "cost_usd": 1.21, "sessions": 2 }
  ],
  "by_task_type": [
    { "task_type": "documentación", "cost_usd": 0.93 },
    { "task_type": null, "cost_usd": 0.91 }
  ],
  "last_snapshot_at": "2026-06-27T13:45:00Z"
}
```

---

### 4.6 `GET /api/usage/history` — histórico

**Query params:** `granularity` (`day`|`week`|`month`), `from`, `to`, `project`, `model`, `task_type`.

```json
{
  "granularity": "day",
  "series": [
    {
      "period": "2026-06-26",
      "cost_usd": 3.12,
      "total_input_tokens": 210400,
      "total_output_tokens": 11200,
      "peak_five_hour_percentage": 78,
      "peak_seven_day_percentage": 41,
      "sessions": 4
    }
  ]
}
```

---

### 4.7 `GET /api/recommendations` — recomendaciones activas

```json
{
  "recommendations": [
    {
      "id": "rec_01",
      "workday_id": "2026-06-27",
      "session_id": "623a283b-...",
      "recommendation_type": "continue",
      "severity": "info",
      "message": "Uso bajo. Continúa trabajando con normalidad.",
      "reason": "Ventana de 5h al 45%, 7d al 7%.",
      "created_at": "2026-06-27T13:45:00Z",
      "acknowledged_at": null
    }
  ]
}
```

`POST /api/recommendations/{id}/ack` → marca como vista. Response: la recomendación con `acknowledged_at` poblado.

**Valores de `recommendation_type`:** `continue` · `reduce_context` · `split_task` · `new_session` · `reserve_for_critical` · `review_project` · `pause` · `switch_provider` (multi-provider, flujo independiente).
**Valores de `severity`:** `info` · `warning` · `critical`.

---

### 4.8 `GET /api/health` — salud del backend y fuentes

```json
{
  "status": "ok",
  "uptime_seconds": 5821,
  "database": "ok",
  "sources": {
    "statusline_hook": { "last_received_at": "2026-06-27T13:45:00Z", "healthy": true },
    "ccusage": { "last_run_at": "2026-06-27T13:40:00Z", "healthy": true }
  },
  "scheduler": { "last_reconciliation_at": "2026-06-27T13:40:00Z", "interval_seconds": 300 }
}
```

---

### 4.9 `WS /api/ws/dashboard` — push en tiempo real

Canal WebSocket que empuja el estado del dashboard. **Al conectar**, el servidor envía de inmediato el payload inicial (misma forma que `GET /api/dashboard`, §4.2). Tras cada **mutación relevante** (nuevo snapshot aceptado, ack de recomendación, anotación de sesión) el backend hace `broadcast()` del estado fresco a todos los clientes conectados.

Es una **optimización de push, no un contrato aparte**: la fuente de verdad sigue siendo la API REST. Un cliente puede ignorar el WebSocket y hacer polling de `GET /api/dashboard` sin perder funcionalidad.

- **Handshake:** `ws(s)://<host>/api/ws/dashboard` (mismo origen; `wss` si el front se sirve por HTTPS).
- **Mensajes del servidor:** JSON con la forma de §4.2.
- **Mensajes del cliente:** ninguno requerido; el canal es unidireccional (solo push).

---

### 4.10 `GET /api/ping` — liveness

Sonda de vida mínima. **Response `200 OK`:** `{ "status": "ok" }`.

---

## 5. Resumen de endpoints

| Método | Endpoint | Consumidor | Propósito |
|---|---|---|---|
| `POST` | `/api/snapshots` | Hook | Ingesta cruda del statusline |
| `GET` | `/api/dashboard` | Front | Vista consolidada |
| `GET` | `/api/sessions/current` | Front | Sesión activa |
| `GET` | `/api/sessions/current/large-files` | Front | Top-5 archivos pesados del proyecto |
| `PATCH` | `/api/sessions/{id}` | Front | Anotar objetivo/tipo de tarea |
| `GET` | `/api/usage/today` | Front | Acumulado del día |
| `GET` | `/api/usage/history` | Front | Histórico |
| `GET` | `/api/recommendations` | Front | Recomendaciones |
| `POST` | `/api/recommendations/{id}/ack` | Front | Marcar vista |
| `GET` | `/api/health` | Front/diagnóstico | Salud del sistema |
| `GET` | `/api/ping` | Diagnóstico | Liveness (`{"status":"ok"}`) |
| `WS` | `/api/ws/dashboard` | Front | Push del dashboard (forma de §4.2) |

---

## 6. Campos pendientes / a resolver en implementación

- **`git_branch`** no viene en el statusline; el backend lo deriva ejecutando `git -C <project_path> rev-parse --abbrev-ref HEAD` (cacheado).
- **`cost_today_usd`** y **`burn_rate`** se calculan en backend (suma del día / pendiente reciente). Son `captured`/`estimated` respectivamente.
- **Cierre de sesión:** por cambio de `session_external_id` o por inactividad (sin snapshots > N min). A definir en implementación.
- **`project_name`** se deriva del basename de `project_path`.