"""Construcción de ``GET /api/dashboard`` (contrato §4.2).

Hito 0: arma la vista desde el último snapshot y la jornada activa. Los campos
aún no implementados (burn_rate, cost_today, by_project, recomendaciones) van en
``null``/vacío — nunca inventados. Se completan en hitos posteriores.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.models import UsageSnapshot, Workday
from app.services.status import derive_status


def _isoformat(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _human_duration(seconds: int | None) -> str | None:
    if seconds is None or seconds < 0:
        return None
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _window(
    pct: float | None, resets_at: datetime | None, now: datetime
) -> dict[str, Any] | None:
    if pct is None and resets_at is None:
        return None
    resets_in_seconds = None
    if resets_at is not None:
        ra = resets_at if resets_at.tzinfo else resets_at.replace(tzinfo=UTC)
        resets_in_seconds = max(0, int((ra - now).total_seconds()))
    return {
        "used_percentage": pct,
        "resets_at": _isoformat(resets_at),
        "resets_in_seconds": resets_in_seconds,
        "resets_in_human": _human_duration(resets_in_seconds),
        "data_quality": "official",
    }


def build_dashboard(session: Session) -> dict[str, Any]:
    now = datetime.now(UTC)
    workday = session.exec(
        select(Workday).where(Workday.status == "active")
    ).first()
    snap = session.exec(
        select(UsageSnapshot).order_by(UsageSnapshot.captured_at.desc())  # type: ignore[attr-defined]
    ).first()

    if snap is None:
        return {
            "generated_at": _isoformat(now),
            "status": "critical",  # sin datos confiables
            "workday": _workday_view(workday),
            "current_session": None,
            "metrics": None,
            "last_snapshot_at": None,
            "recommendations": [],
        }

    status = derive_status(snap.rate_limit_5h_percentage, snap.rate_limit_7d_percentage)
    return {
        "generated_at": _isoformat(now),
        "status": status,
        "workday": _workday_view(workday),
        "current_session": {
            "id": snap.session_external_id,
            "session_name": snap.session_name,
            "project_name": _basename(snap.project_path),
            "project_path": snap.project_path,
            "model_name": snap.model_name,
            "git_branch": None,  # derivado en Hito 1
            "effort_level": snap.effort_level,
            "task_type": None,  # manual, Hito 1
            "objective": None,  # manual, Hito 1
            "started_at": None,  # sesión persistida en Hito 1
        },
        "metrics": {
            "model_name": snap.model_name,
            "cost_session_usd": snap.cost_session_usd,
            "cost_today_usd": None,  # Hito 2
            "burn_rate_usd_per_hour": None,  # Hito 2 (estimated)
            "tokens": {
                "total_input_tokens": snap.total_input_tokens,
                "total_output_tokens": snap.total_output_tokens,
                "cache_creation_input_tokens": snap.cache_creation_input_tokens,
                "cache_read_input_tokens": snap.cache_read_input_tokens,
            },
            "context": {
                "used_percentage": snap.context_used_percentage,
                "remaining_percentage": (
                    None
                    if snap.context_used_percentage is None
                    else 100 - snap.context_used_percentage
                ),
                "context_window_size": snap.context_window_size,
            },
            "five_hour": _window(
                snap.rate_limit_5h_percentage, snap.rate_limit_5h_resets_at, now
            ),
            "seven_day": _window(
                snap.rate_limit_7d_percentage, snap.rate_limit_7d_resets_at, now
            ),
        },
        "last_snapshot_at": _isoformat(snap.captured_at),
        "recommendations": [],  # Hito 4
    }


def _workday_view(workday: Workday | None) -> dict[str, Any] | None:
    if workday is None:
        return None
    return {
        "id": workday.id,
        "date": workday.date,
        "started_at": _isoformat(workday.started_at),
        "status": workday.status,
        "initial_state": workday.initial_state,
        "current_state": workday.current_state,
    }


def _basename(path: str | None) -> str | None:
    if not path:
        return None
    return path.rstrip("/").rsplit("/", 1)[-1]
