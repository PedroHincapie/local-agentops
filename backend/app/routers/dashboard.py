"""``GET /api/dashboard`` — vista consolidada que consume el frontend."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db import get_session
from app.services.dashboard import build_dashboard

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
def get_dashboard(session: Session = Depends(get_session)) -> dict[str, Any]:
    return build_dashboard(session)
