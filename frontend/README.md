# Local AgentOps — Dashboard (frontend)

Dashboard web de observabilidad operativa para **coding agents**. Versión v0.1, provider único: **Claude Code**.

Es una herramienta **local y de un solo usuario**. Responde de un vistazo a tres preguntas:

> ¿Cuánto margen de uso me queda, cuánto he consumido, y debo continuar, reducir contexto o pausar?

---

## Qué es esto (y qué no)

- **Es** una SPA de una sola pantalla en vivo que consume **un único endpoint**: `GET /api/dashboard`.
- **No** tiene base de datos, login ni estado de servidor propio. Todo lo que muestra viene de ese endpoint.
- El foco visual son las **dos ventanas de límite oficiales** (`five_hour` y `seven_day`): son el "margen operativo" del usuario.

El frontend es un solo archivo autocontenido: **`AgentOps Dashboard.dc.html`** (se abre directo en el navegador). `dashboard.json` es una copia del contrato usada como mock/respaldo.

---

## Contrato de datos — `GET /api/dashboard`

El frontend espera **exactamente** esta forma. Los nombres de campo son parte del contrato: no renombrar.

```json
{
  "generated_at": "2026-06-27T13:45:12Z",
  "status": "green",
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
      "resets_in_human": "3h 14m",
      "data_quality": "official"
    },
    "seven_day": {
      "used_percentage": 7,
      "resets_at": "2026-07-03T07:00:00Z",
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
    }
  ]
}
```

### Campos y cómo los usa la UI

| Campo | Tipo | Uso en la pantalla |
|---|---|---|
| `status` | `"green" \| "yellow" \| "red" \| "critical"` | **Derivan de aquí** el color del pill de estado, el relleno de los gauges y el banner de alerta. Es el campo que cambia toda la lectura visual. |
| `metrics.five_hour` / `metrics.seven_day` | objeto | **Elemento protagonista** — gauges grandes. Se usan `used_percentage`, `resets_in_human` y `data_quality`. |
| `…data_quality` | `"official" \| ...` | Badge de la ventana: `official` → **OFICIAL**; cualquier otro → **ESTIMADO** (ámbar). |
| `metrics.cost_session_usd` | número | Tarjeta "Costo sesión" (3 decimales). |
| `metrics.cost_today_usd` | número | Tarjeta "Costo del día" (2 decimales). |
| `metrics.burn_rate_usd_per_hour` | número | Tarjeta "Burn rate" ($/h). |
| `metrics.context` | objeto | Tarjeta "Contexto": `used_percentage` sobre `context_window_size`. |
| `metrics.tokens.*` | número | Barra apilada + desglose (input / output / cache creation / cache read). |
| `current_session.*` | objeto | Tarjeta "Sesión actual" (nombre, ruta, rama git, modelo, esfuerzo). |
| `current_session.objective` / `task_type` | `string \| null` | Campos **editables** por el usuario. Hoy `null`; ver "Anotaciones" abajo. |
| `recommendations[]` | array | Panel de recomendaciones. Color por `severity` (`info` / `warning` / `critical`). |
| `generated_at` / `last_snapshot_at` | ISO 8601 | Se muestran como referencia del snapshot. |

### Semántica de `status` (contrato visual)

- **green** — uso bajo/normal. Sin alarmas.
- **yellow** — uso medio o tendencia acelerada. Acento de advertencia.
- **red** — uso alto, poco margen. Aparece **banner** de aviso.
- **critical** — límite alcanzado o **sin datos confiables**. Estado de bloqueo, el más prominente (banner con pulso).

> El backend es responsable de calcular `status` a partir del consumo real. El frontend solo lo pinta.

---

## Cómo se conectan front y back

El frontend hace **polling** cada **10 s** a `API_URL` (definido al inicio de la clase `Component`, dentro de `AgentOps Dashboard.dc.html`):

```js
API_URL = 'http://127.0.0.1:8787/api/dashboard';
POLL_MS = 10000;
```

Estados de conexión que muestra la barra superior:

- **Conectando…** — primera lectura en curso.
- **En vivo** — última lectura OK (< 30 s).
- **Datos antiguos** — pasaron > 30 s sin lectura correcta.
- **Sin conexión — reintentando** — el fetch falló; reintenta solo en el siguiente ciclo.
- **Mock embebido (sin backend)** — no se pudo alcanzar el API y no había datos previos; usa una copia local del contrato para no quedar en blanco.

### CORS (requisito)

El dashboard y el API viven en orígenes distintos, así que FastAPI debe permitir CORS:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # o restringe al origen del dashboard
    allow_methods=["GET"],
    allow_headers=["*"],
)
```

**Alternativa sin CORS:** servir `AgentOps Dashboard.dc.html` como archivo estático desde el propio FastAPI (mismo origen). En ese caso `API_URL` puede ser relativo: `'/api/dashboard'`.

---

## Ejecutar el backend

```bash
cd /Users/imagemaker/Documents/Proyectos/Personal/proyecto-agentOps/backend
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8787
# en desarrollo: agrega --reload
```

Endpoints de referencia:

- Ping: `http://127.0.0.1:8787/api/ping`
- Dashboard (JSON): `http://127.0.0.1:8787/api/dashboard`
- Swagger: `http://127.0.0.1:8787/docs`

> Nota: hoy el proceso se levanta a mano; si se reinicia el equipo o se cierra, se cae (el LaunchAgent permanente no está instalado).

---

## Anotaciones del usuario (objetivo / tipo de tarea)

`current_session.objective` y `current_session.task_type` son editables desde la UI. Hoy se guardan **solo en el navegador** (`localStorage`), no viajan al backend, y no se pisan con cada poll.

**Pendiente de backend:** un endpoint de escritura para persistirlas del lado servidor, p. ej.:

```
POST /api/session/annotations
{ "session_id": "...", "objective": "...", "task_type": "..." }
```

Cuando exista, el frontend puede enviarlas ahí en vez de (o además de) `localStorage`.

---

## Estructura del frontend

```
AgentOps Dashboard.dc.html   # la SPA completa (abre directo en navegador)
dashboard.json               # copia del contrato (mock / referencia)
README.md                    # este archivo
```

Para **cambiar de endpoint**: editar `API_URL` en la clase `Component` dentro del `.dc.html`.
Para **previsualizar estados** sin backend: editar `status` y los valores de `metrics.*` en `dashboard.json` (o en la constante `MOCK` embebida en el `.dc.html`).

---

## Roadmap (siguiente iteración)

- **Histórico**: sparklines de burn rate y de las dos ventanas a lo largo del día.
- **Persistencia de anotaciones** vía endpoint de escritura.
- Separar visualmente "límite alcanzado" de "sin datos confiables" dentro de `critical`.
- Acciones rápidas en el banner crítico (compactar contexto, copiar resumen de sesión).
