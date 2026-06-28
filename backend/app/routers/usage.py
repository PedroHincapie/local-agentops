"""``GET /api/usage/today`` (§4.5) y ``GET /api/usage/history`` (§4.6)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.db import get_session
from app.services import usage_reports

router = APIRouter(prefix="/api/usage", tags=["usage"])


@router.get("/today")
def usage_today(db: Session = Depends(get_session)) -> dict:
    return usage_reports.build_usage_today(db)


@router.get("/history")
def usage_history(
    granularity: str = Query("day", pattern="^(day|week|month)$"),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    project: str | None = Query(None),
    model: str | None = Query(None),
    task_type: str | None = Query(None),
    db: Session = Depends(get_session),
) -> dict:
    return usage_reports.build_usage_history(
        db,
        granularity=granularity,
        date_from=from_,
        date_to=to,
        project=project,
        model=model,
        task_type=task_type,
    )
