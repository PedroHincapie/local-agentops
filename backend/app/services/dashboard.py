"""Construcción de ``GET /api/dashboard`` (contrato §4.2).

Hito 0: arma la vista desde el último snapshot y la jornada activa. Los campos
aún no implementados (burn_rate, cost_today, by_project, recomendaciones) van en
``null``/vacío — nunca inventados. Se completan en hitos posteriores.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.models import AgentSession, Project, UsageSnapshot, Workday
from app.services.sessions import current_session
from app.services.status import derive_status
from app.services.usage import burn_rate_usd_per_hour, cost_today_usd


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
    # Feed oficial en vivo: el último snapshot del statusline. Los ticks de ccusage
    # (reconciliación, sin rate_limits) no deben degradar status ni ventanas.
    snap = session.exec(
        select(UsageSnapshot)
        .where(UsageSnapshot.source_name == "statusline")
        .order_by(UsageSnapshot.captured_at.desc())  # type: ignore[attr-defined]
    ).first()
    # last_snapshot_at refleja CUALQUIER fuente (incluida la reconciliación ccusage).
    last_any = session.exec(
        select(UsageSnapshot).order_by(UsageSnapshot.captured_at.desc())  # type: ignore[attr-defined]
    ).first()

    if snap is None:
        return {
            "generated_at": _isoformat(now),
            "status": "critical",  # sin datos confiables del feed en vivo
            "workday": _workday_view(workday),
            "current_session": None,
            "metrics": None,
            "last_snapshot_at": _isoformat(last_any.captured_at) if last_any else None,
            "recommendations": [],
        }

    status = derive_status(snap.rate_limit_5h_percentage, snap.rate_limit_7d_percentage)
    agent_session = current_session(session)
    return {
        "generated_at": _isoformat(now),
        "status": status,
        "workday": _workday_view(workday),
        "current_session": _current_session_view(session, snap, agent_session),
        "metrics": {
            "model_name": snap.model_name,
            "cost_session_usd": snap.cost_session_usd,
            "cost_today_usd": cost_today_usd(session, snap.workday_id),
            "burn_rate_usd_per_hour": burn_rate_usd_per_hour(snap, agent_session, now),
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
        "last_snapshot_at": _isoformat(last_any.captured_at if last_any else snap.captured_at),
        "recommendations": [],  # Hito 4
    }


def _current_session_view(
    session: Session, snap: UsageSnapshot, agent_session: AgentSession | None
) -> dict[str, Any]:
    """current_session del dashboard (§4.2): combina la sesión persistida (git_branch,
    métricas manuales, started_at) con datos del último snapshot (nombre, effort)."""
    project = (
        session.get(Project, agent_session.project_id)
        if agent_session and agent_session.project_id
        else None
    )
    return {
        "id": agent_session.session_external_id if agent_session else snap.session_external_id,
        "session_name": snap.session_name,
        "project_name": project.name if project else _basename(snap.project_path),
        "project_path": snap.project_path,
        "model_name": agent_session.model if agent_session else snap.model_name,
        "git_branch": agent_session.git_branch if agent_session else None,
        "effort_level": snap.effort_level,
        "task_type": agent_session.task_type if agent_session else None,
        "objective": agent_session.objective if agent_session else None,
        "started_at": _isoformat(agent_session.started_at) if agent_session else None,
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
