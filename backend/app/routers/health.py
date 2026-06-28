"""``GET /api/health`` (§4.8)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db import get_session
from app.services.health import build_health

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_session)) -> dict:
    return build_health(db)
