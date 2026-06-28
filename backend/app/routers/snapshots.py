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
    return JSONResponse(status_code=202, content=result)
