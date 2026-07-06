"""``POST /api/snapshots`` — ingesta cruda del statusline (idempotente)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session

from app.db import get_session
from app.services import snapshots as snapshots_service

router = APIRouter(prefix="/api", tags=["snapshots"])


@router.post("/snapshots", status_code=202)
async def post_snapshot(
    request: Request, session: Session = Depends(get_session)
) -> JSONResponse:
    # El hook envía el JSON crudo tal cual. Tolerante a body vacío/no-JSON.
    try:
        raw: Any = await request.json()
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    result = snapshots_service.ingest(session, raw)

    # Reconstruye el dashboard con el nuevo snapshot y lo transmite en tiempo real
    try:
        from app.services.dashboard import build_dashboard
        from app.services.websocket import manager
        db_data = build_dashboard(session)
        await manager.broadcast(db_data)
    except Exception:
        # Fallback silencioso para no bloquear la ingesta si falla la transmisión
        pass

    return JSONResponse(status_code=202, content=result)
