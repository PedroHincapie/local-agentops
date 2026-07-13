"""Cierre de sesión por inactividad (configurable + barrido proactivo).

Antes: el cierre estaba hardcodeado a 120 min y solo se disparaba de forma perezosa
al consultar /api/sessions/current (que el front no usa). Ahora es configurable y el
reconciliador lo barre proactivamente.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import engine, init_db
from app.main import app
from app.models import AgentSession, UsageSnapshot
from app.services.reconciler import reconcile_once
from app.services.sessions import close_idle_sessions, current_session

client = TestClient(app)


def _backdate_last_snapshot(minutes: int) -> None:
    """Envejece el snapshot más reciente para simular inactividad."""
    with Session(engine) as db:
        snap = db.exec(
            select(UsageSnapshot).order_by(UsageSnapshot.captured_at.desc())  # type: ignore[attr-defined]
        ).first()
        assert snap is not None
        snap.captured_at = datetime.now(UTC) - timedelta(minutes=minutes)
        db.add(snap)
        db.commit()


def _active_count() -> int:
    with Session(engine) as db:
        return len(
            db.exec(select(AgentSession).where(AgentSession.status == "active")).all()
        )


def test_close_idle_sessions_cierra_la_inactiva(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)
    assert _active_count() == 1

    _backdate_last_snapshot(minutes=180)  # > 120 min (default)

    with Session(engine) as db:
        closed = close_idle_sessions(db)
    assert closed == 1
    assert _active_count() == 0


def test_close_idle_sessions_respeta_sesion_reciente(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)

    with Session(engine) as db:
        closed = close_idle_sessions(db)  # snapshot recién creado -> no cierra
    assert closed == 0
    assert _active_count() == 1


def test_current_session_cierre_perezoso(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)
    _backdate_last_snapshot(minutes=180)

    with Session(engine) as db:
        assert current_session(db) is None  # cierra y no la devuelve
    assert _active_count() == 0


class _NoopSource:
    """Fuente de prueba que no aporta datos (evita invocar el ccusage real)."""

    name = "ccusage"
    provider = "claude"
    source_name = "ccusage"

    def fetch(self) -> None:
        return None


def test_reconciler_barre_sesiones_inactivas(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)
    _backdate_last_snapshot(minutes=180)

    # El barrido corre dentro de reconcile_once, aunque la fuente no aporte datos.
    reconcile_once(_NoopSource())
    assert _active_count() == 0
