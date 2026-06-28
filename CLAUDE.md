# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

This repo is currently **spec-only**. It contains:
- `README.md` — full product/vision spec, in Spanish (**Codex-centric, see divergence note below**).
- `docs/API_CONTRACT.md` — the **authoritative REST contract** for the Claude Code MVP (front/back agreement).
- `CLAUDE.md` (this file) and `.gitignore`.

No backend, frontend, build config, or tests exist yet. The `.gitignore` already anticipates the stack: Python (pytest, ruff, mypy, `.venv`) and Node/Vite. When implementing, follow the architecture below.

> **Documentation divergence — read this first.** `README.md` describes an **earlier vision** where **Codex** (ChatGPT-account auth) was the MVP provider, with a multi-provider schema (`providers`, `provider_capabilities` tables), port `8000`, and APScheduler as the *primary* capture. The project has since **pivoted to Claude Code only** (statusline hook as primary capture, `ccusage` as reconciler, no multi-provider layer, port `8787`). **For the MVP, this file + `docs/API_CONTRACT.md` are the source of truth, not the README's API/schema sections.** Rewriting `README.md` to match the Claude Code design is pending work; until then, when the README conflicts with this file or the contract, the contract wins.

## What this is

**Local AgentOps** is a **local-first, single-user** observability tool for coding agents. The MVP supports only **Claude Code**. It captures, persists, aggregates, and visualizes Claude Code usage (rate-limit windows, tokens, context, cost, sessions) so a developer can see how much operational margin they have left during the day. No central server, no external telemetry — every user runs their own instance against their own local data.

## Architecture (single local process)

The whole system runs as **one FastAPI/Uvicorn process on one local port** (`http://localhost:8787`) that serves both the REST API and the compiled frontend as static files. There is no second server and no CORS in normal operation (CORS is only enabled when running the frontend separately under Vite in dev).

Data capture is **hybrid**:
- **Statusline hook (primary, push):** a script wired into `~/.claude/settings.json` renders the user's normal statusline AND, *fire-and-forget*, forwards the per-tick JSON to `POST /api/snapshots`. This path is **never allowed to block** the statusline render — a slow hook freezes the user's terminal. Forwarding must happen in the background or via a spool file the backend drains. The **hook is dumb**: it forwards the raw statusline JSON unchanged; all mapping/normalization lives in the backend (see `docs/API_CONTRACT.md` §2).
- **APScheduler reconciler (safety net, pull):** a job every 5 minutes calls `ccusage` (`ccusage blocks --active --json`, `ccusage session --json`) to recover usage that occurred while the backend was down and to recompute aggregates. This is reconciliation, **not** primary capture.

All capture sources sit behind a single internal interface, **`CaptureSource` (`fetch() -> NormalizedSnapshot`)**. This is the *only* abstraction deliberately kept from the abandoned multi-provider design — it isolates source volatility without reintroducing a provider layer. Adding/swapping a source must not touch the dashboard.

Flow: `Claude Code → hook → POST /api/snapshots → normalizer → SQLite → recommendation engine → API → frontend SPA`.

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
- **Frontend (by contract):** delivered by **Claude Design** with its own stack (typically React + Vite). It is a static SPA served by the backend and consumes only the documented REST API. The **API contract in `docs/API_CONTRACT.md` (endpoints + JSON shape) is the stable agreement** between front and back; do not couple the backend to frontend internals.

## Data model & API

- **Schema:** the SQLite tables (`projects`, `workdays`, `agent_sessions`, `usage_snapshots`, `usage_events`, `recommendations`) are described in `README.md` under "Modelo de datos inicial" — **but ignore the `providers` / `provider_capabilities` tables**, which belong to the abandoned multi-provider design. `usage_snapshots` is the core table.
- **Endpoints & JSON shapes:** the **authoritative contract is `docs/API_CONTRACT.md` §4–5** (`POST /api/snapshots`, `GET /api/dashboard`, `GET /api/sessions/current`, `PATCH /api/sessions/{id}`, `GET /api/usage/today`, `GET /api/usage/history`, `GET /api/recommendations`, `POST /api/recommendations/{id}/ack`, `GET /api/health`). The README's "API local propuesta" section lists a **different, Codex-era** endpoint set (`/api/snapshots/capture`, `/api/providers`, …) — do **not** build to it.
- `git_branch` is **not** in the statusline; derive it via `git -C <project_path> rev-parse --abbrev-ref HEAD` (cached). `cost_today_usd` (captured) and `burn_rate` (estimated) are computed in the backend. `project_name` is the basename of `project_path`.

## Build / test / run

No tooling is committed yet. Per the spec and `.gitignore`, the expected setup once implemented:
- Backend: Python virtualenv (`.venv`), `pytest` for tests, `ruff` for lint, `mypy` for types. Run with `uvicorn`.
- Frontend: Node + Vite (`npm run dev` / build to static, copied into the backend's served directory).
- Install requires Claude Code (ideally v1.2.80+) and `ccusage` available via `npx`/`bunx` (no global install).

When you add these, document the actual commands here (including how to run a single test).

## Conventions

- The README and all product docs are written in **Spanish**. Match that language for user-facing docs and commit messages in the existing style (e.g. `docs: define Local AgentOps product and architecture`).
- Build the MVP as a **walking skeleton first**: one hook snapshot → persisted in SQLite → visible on the dashboard, before fleshing out the normalizer, reconciler, and recommendation engine.
- Reconciling `README.md` with the Claude Code design is pending; if you touch product docs, prefer aligning them to this file + `docs/API_CONTRACT.md` rather than the other way around.
