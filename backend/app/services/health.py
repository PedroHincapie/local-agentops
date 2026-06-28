"""``GET /api/health`` (§4.8): salud del backend, la BD y las fuentes de captura."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, func, select

from app.config import settings
from app.models import UsageSnapshot, Workday
from app.services.reconciler_state import state

# Inicio del proceso (para uptime). Se fija al importar el módulo, en el arranque.
_STARTED_AT = datetime.now(UTC)


def _isoformat(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_health(db: Session) -> dict[str, Any]:
    try:
        db.exec(select(func.count()).select_from(Workday)).one()
        database = "ok"
    except Exception:
        database = "error"

    last_statusline = db.exec(
        select(UsageSnapshot)
        .where(UsageSnapshot.source_name == "statusline")
        .order_by(UsageSnapshot.captured_at.desc())  # type: ignore[attr-defined]
    ).first()
    last_received_at = last_statusline.captured_at if last_statusline else None

    now = datetime.now(UTC)
    return {
        "status": "ok" if database == "ok" else "degraded",
        "uptime_seconds": int((now - _STARTED_AT).total_seconds()),
        "database": database,
        "sources": {
            "statusline_hook": {
                "last_received_at": _isoformat(last_received_at),
                "healthy": last_received_at is not None,
            },
            "ccusage": {
                "last_run_at": _isoformat(state.last_run_at),
                # None = aún no corrió; nunca se asume sano sin evidencia.
                "healthy": state.healthy,
            },
        },
        "scheduler": {
            "last_reconciliation_at": _isoformat(state.last_run_at),
            "interval_seconds": settings.reconcile_interval_seconds,
        },
    }
