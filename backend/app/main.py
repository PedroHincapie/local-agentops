"""Punto de entrada FastAPI: un único proceso que sirve API + SPA estático.

Sin CORS en operación normal (un solo origen). El reconciliador APScheduler y el
montaje del SPA se conectan en hitos posteriores; aquí queda preparado.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import init_db
from app.routers import (
    dashboard,
    health,
    recommendations,
    sessions,
    snapshots,
    usage,
)
from app.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    start_scheduler()  # reconciliador ccusage cada N min (no-op si scheduler_enabled=false)
    yield
    stop_scheduler()


app = FastAPI(title="Local AgentOps", version="0.1.0", lifespan=lifespan)

# CORS solo en desarrollo (dashboard abierto desde otro origen). En producción el
# backend sirve el SPA en el mismo origen y esto queda apagado (AGENTOPS_DEV_CORS=false).
if settings.dev_cors:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

app.include_router(snapshots.router)
app.include_router(dashboard.router)
app.include_router(sessions.router)
app.include_router(recommendations.router)
app.include_router(usage.router)
app.include_router(health.router)


@app.get("/api/ping")
def ping() -> dict[str, str]:
    return {"status": "ok"}


# Sirve el SPA compilado solo si existe el build (Claude Design lo entrega aparte).
_dist = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", settings.frontend_dist))
if os.path.isdir(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="spa")
