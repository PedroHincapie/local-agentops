"""Agregados de uso derivados en el backend (contrato §6).

- ``cost_today_usd`` (captured): el statusline reporta ``cost.total_cost_usd``
  **acumulado por sesión**, así que el costo del día es la suma del costo máximo
  por sesión de la jornada (no la suma de todos los ticks, que lo inflaría).
- ``burn_rate_usd_per_hour`` (estimated): costo de la sesión sobre las horas
  activas. Si hay muy poca duración para estimar con confianza, devuelve ``None``
  (CLAUDE.md: nunca inventar; lo no estimable degrada a "no disponible").
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Session, func, select

from app.models import AgentSession, UsageSnapshot

# Duración mínima para que un burn rate sea fiable: por debajo, el cociente se
# dispara y no representa una tasa real.
_MIN_BURN_SECONDS = 60


def cost_today_usd(db: Session, workday_id: str) -> float | None:
    """Suma del costo máximo (acumulado) por sesión en la jornada. None si no hay datos."""
    rows = db.exec(
        select(func.max(UsageSnapshot.cost_session_usd))
        .where(UsageSnapshot.workday_id == workday_id)
        .where(UsageSnapshot.cost_session_usd.is_not(None))  # type: ignore[union-attr]
        .group_by(UsageSnapshot.session_id)
    ).all()
    costs = [c for c in rows if c is not None]
    if not costs:
        return None
    return round(sum(costs), 6)


def burn_rate_usd_per_hour(
    snap: UsageSnapshot, agent_session: AgentSession | None, now: datetime
) -> float | None:
    """Costo por hora activa de la sesión actual. None si no hay base fiable."""
    cost = snap.cost_session_usd
    if cost is None:
        return None

    seconds: float | None = None
    if snap.session_duration_ms is not None and snap.session_duration_ms > 0:
        seconds = snap.session_duration_ms / 1000
    elif agent_session is not None:
        started = agent_session.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        seconds = (now - started).total_seconds()

    if seconds is None or seconds < _MIN_BURN_SECONDS:
        return None
    return round(cost / (seconds / 3600), 4)
