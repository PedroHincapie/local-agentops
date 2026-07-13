# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

The **MVP is implemented and running on branch `main`** (Hitos 0–4 + all §4 contract endpoints; 43 backend tests passing). The repo contains:
- `backend/` — FastAPI app (`app/`), tests (`tests/`), `pyproject.toml`. See "Build / test / run" below.
- `frontend/public/` — the static SPA (`index.html` + `support.js`) served by the backend at `/` (default `AGENTOPS_FRONTEND_DIST=../frontend/public`).
- `hook/statusline-hook.sh` — the statusline hook wired into `~/.claude/settings.json` (primary capture).
- `deploy/` — deployment assets (e.g. LaunchAgent).
- `docs/API_CONTRACT.md` — the **authoritative REST contract** for the Claude Code MVP (front/back agreement).
- `docs/INSTALL.md` — local install/run guide (backend + hook wiring).
- `README.md` — product/vision spec, in Spanish (aligned to the Claude Code design).
- `CLAUDE.md` (this file) and `.gitignore`.

> **Branch note.** `feat/walking-skeleton` is the historical skeleton branch; **`main` is now ahead of it** and is the active branch (it merged the frontend and real-time WebSocket push). Work on `main`.

The **frontend lives in this repo** at `frontend/public/` and is served on the same origin as the API (no CORS in normal operation). Capture is live: the hook forwards each statusline tick to `POST /api/snapshots`; the APScheduler reconciler runs every 5 min; dashboard updates are pushed to connected clients over a **WebSocket** (`/ws/dashboard`).

> **Source of truth.** The project targets **Claude Code only** (statusline hook as primary capture, `ccusage` as reconciler, no multi-provider layer, port `8787`). `README.md` has been **reconciled** to this design. The historical Codex-era vision (ChatGPT-account auth, `providers`/`provider_capabilities` tables, port `8000`, APScheduler as *primary* capture) is **not** the MVP. For endpoint/JSON details, **`docs/API_CONTRACT.md` is authoritative**; when any doc conflicts with the contract, the contract wins.

## What this is

**Local AgentOps** is a **local-first, single-user** observability tool for coding agents. The MVP supports only **Claude Code**. It captures, persists, aggregates, and visualizes Claude Code usage (rate-limit windows, tokens, context, cost, sessions) so a developer can see how much operational margin they have left during the day. No central server, no external telemetry — every user runs their own instance against their own local data.

## Architecture (single local process)

The whole system runs as **one FastAPI/Uvicorn process on one local port** (`http://localhost:8787`) that serves both the REST API and the compiled frontend as static files. There is no second server and no CORS in normal operation (CORS is only enabled when running the frontend separately under Vite in dev).

Data capture is **hybrid**:
- **Statusline hook (primary, push):** a script wired into `~/.claude/settings.json` renders the user's normal statusline AND, *fire-and-forget*, forwards the per-tick JSON to `POST /api/snapshots`. This path is **never allowed to block** the statusline render — a slow hook freezes the user's terminal. Forwarding must happen in the background or via a spool file the backend drains. The **hook is dumb**: it forwards the raw statusline JSON unchanged; all mapping/normalization lives in the backend (see `docs/API_CONTRACT.md` §2).
- **APScheduler reconciler (safety net, pull):** a job every 5 minutes calls `ccusage` (`ccusage blocks --active --json`, `ccusage session --json`) to recover usage that occurred while the backend was down and to recompute aggregates. This is reconciliation, **not** primary capture.

All capture sources sit behind a single internal interface, **`CaptureSource` (`fetch() -> NormalizedSnapshot`)**. This is the *only* abstraction deliberately kept from the abandoned multi-provider design — it isolates source volatility without reintroducing a provider layer. Adding/swapping a source must not touch the dashboard.

**Real-time push:** a `ConnectionManager` (`app/services/websocket.py`) holds the connected dashboard clients; the `snapshots`, `recommendations`, and `sessions` routers `broadcast()` the fresh state after a mutation, and the `/ws/dashboard` endpoint (in the `dashboard` router) sends the initial payload on connect. The REST endpoints remain the source of truth; the WebSocket is a push optimization, not a separate contract.

Flow: `Claude Code → hook → POST /api/snapshots → normalizer → SQLite → recommendation engine → API + WebSocket push → frontend SPA`.

## Key invariants (do not violate)

- **No multi-provider layer in the MVP.** Claude Code is the only provider. Keep the product clean; the future provider abstraction stays parked behind `CaptureSource` only. (The README's `providers` / `provider_capabilities` tables are **not** part of the MVP schema.)
- **Every persisted datum is classified by origin** via `source_type` / `data_quality`: `official` | `captured` | `estimated` | `manual`, plus `source_name` (`statusline` | `ccusage` | `manual`). **Never invent a value.** If a source fails, mark `data_quality` and keep the dashboard working — the missing metric degrades to "unavailable", not to a guess.
- The canonical "usage remaining" comes from the statusline's native **`rate_limits.five_hour` / `rate_limits.seven_day`** fields (these match Anthropic's plan UI). Operational `status` is derived from the **max** of the two windows' `used_percentage` (green <50, yellow <80, red <95, critical ≥95; no rate-limit data ⇒ critical, never invented). The internal OAuth usage endpoint is **explicitly not used** in the MVP.
- `rate_limits` requires **Claude Code v1.2.80+**. On older versions, window metrics are unavailable (degrade gracefully).
- **Snapshot dedup:** consecutive identical ticks are discarded by content hash `(session_external_id + cost + rate_limits + context)` to avoid inflating the time series. `/api/snapshots` must be **idempotent and non-blocking**.
- Persistence is **SQLite only** (local file, zero-cost, single user — a correct choice, not a placeholder). Use UUID ids. Keep all logic in the backend: no DB triggers or stored procedures.
- Workdays and sessions are **auto-detected** (first snapshot of the day opens a workday; a new `session_id` opens a session bound to the project via `cwd`/`project_dir`). The user only optionally annotates `objective` and `task_type` — the only `manual` metrics.

## Stack

- **Backend (fixed):** FastAPI + Uvicorn, APScheduler (5-min reconciler job), SQLite via SQLModel/SQLAlchemy + Pydantic, httpx/subprocess to invoke `ccusage`. Config via `.env` (+ optional YAML for state thresholds).
- **Frontend (by contract):** a static SPA that lives in-repo at `frontend/public/` (`index.html` + `support.js`, no build step) and is served by the backend at `/`. It consumes the documented REST API plus the `/ws/dashboard` WebSocket. The **API contract in `docs/API_CONTRACT.md` (endpoints + JSON shape) is the stable agreement** between front and back; do not couple the backend to frontend internals. (Originally scoped as a Claude Design deliverable built with React + Vite; the current SPA is served straight from `frontend/public/`.)

## Data model & API

- **Schema:** the SQLite tables (`projects`, `workdays`, `agent_sessions`, `usage_snapshots`, `usage_events`, `recommendations`) are described in `README.md` under "Modelo de datos inicial" — **but ignore the `providers` / `provider_capabilities` tables**, which belong to the abandoned multi-provider design. `usage_snapshots` is the core table.
- **Endpoints & JSON shapes:** the **authoritative contract is `docs/API_CONTRACT.md` §4–5** (`POST /api/snapshots`, `GET /api/dashboard`, `GET /api/sessions/current`, `PATCH /api/sessions/{id}`, `GET /api/usage/today`, `GET /api/usage/history`, `GET /api/recommendations`, `POST /api/recommendations/{id}/ack`, `GET /api/health`). There is also a `GET /api/ping` liveness probe and the `/ws/dashboard` WebSocket (push channel, payload = the `GET /api/dashboard` shape). The README's "API local propuesta" section lists a **different, Codex-era** endpoint set (`/api/snapshots/capture`, `/api/providers`, …) — do **not** build to it.
- `git_branch` is **not** in the statusline; derive it via `git -C <project_path> rev-parse --abbrev-ref HEAD` (cached). `cost_today_usd` (captured) and `burn_rate` (estimated) are computed in the backend. `project_name` is the basename of `project_path`.

## Build / test / run

All commands run from `backend/` with the project virtualenv (`.venv`). Deps live in `pyproject.toml` (`.[dev]` for pytest/ruff/mypy). Full install/wiring guide in `docs/INSTALL.md`.

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

# Run the server (API + static SPA on http://127.0.0.1:8787)
uvicorn app.main:app --host 127.0.0.1 --port 8787          # add --reload in dev

# Quality gates (all three must pass before committing)
python -m pytest -q                                        # whole suite
python -m pytest tests/test_workday.py::test_dia_nuevo_cierra_jornada_anterior  # a single test
ruff check app tests
mypy app
```

- **Config:** copy `.env.example` → `.env` (host/port, thresholds, reconciler interval, `AGENTOPS_SCHEDULER_ENABLED`). Env vars are prefixed `AGENTOPS_`.
- **DB:** SQLite file at `backend/data/local-agentops.db` (WAL), auto-created on startup via `init_db()`. No migrations tool (SQLModel `create_all`); to reset, delete the `.db`/`-wal`/`-shm` files.
- **Tests** use a temp SQLite file and disable the scheduler (see `tests/conftest.py`); each test starts on a clean DB.
- **Install** requires Claude Code (ideally v1.2.80+ for `rate_limits`) and `ccusage` via `npx`/`bunx` (no global install).
- **Frontend:** static assets in `frontend/public/` (no build step); the backend mounts `AGENTOPS_FRONTEND_DIST` (default `../frontend/public`) at `/` if the directory exists. To serve a different build, point `AGENTOPS_FRONTEND_DIST` at that directory.

## Conventions

- The README and all product docs are written in **Spanish**. Match that language for user-facing docs and commit messages in the existing style (e.g. `docs: define Local AgentOps product and architecture`).
- The MVP was built **walking-skeleton first** (one hook snapshot → SQLite → dashboard) and that skeleton is now complete; the normalizer, reconciler, recommendation engine, and WebSocket push are all in place. Keep new work incremental and behind the same seams.
- `README.md` has been reconciled to the Claude Code design (Claude-Code-only, port 8787, in-repo `frontend/public/` SPA, WebSocket push). If you touch product docs, keep aligning them to this file + `docs/API_CONTRACT.md` rather than the other way around.
