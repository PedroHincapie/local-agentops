"""Ingesta de snapshots: dedup, auto-apertura de jornada, persistencia.

``POST /api/snapshots`` debe ser idempotente y no bloqueante. Aquí va la lógica;
el router solo orquesta.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.models import UsageSnapshot, Workday
from app.normalizer import normalize
from app.services.status import derive_status


def _today_local() -> str:
    # MVP: una sola jornada activa por día; fecha local del host.
    return datetime.now().date().isoformat()


def get_or_create_workday(session: Session) -> Workday:
    date = _today_local()
    workday = session.exec(select(Workday).where(Workday.date == date)).first()
    if workday is None:
        workday = Workday(date=date, status="active")
        session.add(workday)
        session.flush()  # asegura id antes de usarlo
    return workday


def last_snapshot_for_session(
    session: Session, session_external_id: str | None
) -> UsageSnapshot | None:
    stmt = select(UsageSnapshot).order_by(UsageSnapshot.captured_at.desc())  # type: ignore[attr-defined]
    if session_external_id is not None:
        stmt = stmt.where(UsageSnapshot.session_external_id == session_external_id)
    return session.exec(stmt).first()


def ingest(session: Session, raw: dict[str, Any]) -> dict[str, Any]:
    """Normaliza, deduplica y persiste un tick crudo. Devuelve el cuerpo §4.1."""
    fields = normalize(raw)
    status = derive_status(
        fields.get("rate_limit_5h_percentage"),
        fields.get("rate_limit_7d_percentage"),
    )

    workday = get_or_create_workday(session)
    if workday.initial_state is None:
        workday.initial_state = status
    workday.current_state = status

    # Dedup: si el último snapshot de la misma sesión tiene el mismo hash, se descarta.
    previous = last_snapshot_for_session(session, fields.get("session_external_id"))
    if previous is not None and previous.content_hash == fields["content_hash"]:
        session.add(workday)
        session.commit()
        return {
            "accepted": True,
            "snapshot_id": None,
            "deduplicated": True,
            "session_external_id": fields.get("session_external_id"),
            "workday_id": workday.id,
            "status": status,
        }

    snapshot = UsageSnapshot(
        workday_id=workday.id,
        captured_at=datetime.now(UTC),
        **fields,
    )
    session.add(snapshot)
    session.add(workday)
    session.commit()
    session.refresh(snapshot)

    return {
        "accepted": True,
        "snapshot_id": snapshot.id,
        "deduplicated": False,
        "session_external_id": snapshot.session_external_id,
        "workday_id": workday.id,
        "status": status,
    }
