"""Rollover de jornada: al abrir la de hoy se cierran las activas de días previos.

Sin esto quedarían varias jornadas ``active`` y el dashboard (que toma la activa)
podría anclarse a un día viejo.
"""
from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import engine, init_db
from app.main import app
from app.models import Workday

client = TestClient(app)


def test_dia_nuevo_cierra_jornada_anterior(raw_statusline: dict) -> None:
    init_db()
    # Jornada vieja quedada como activa (simula un día anterior sin cerrar).
    with Session(engine) as s:
        s.add(Workday(date="2020-01-01", status="active"))
        s.commit()

    # El primer tick de hoy abre la jornada de hoy y debe cerrar la vieja.
    client.post("/api/snapshots", json=raw_statusline)

    today = datetime.now().date().isoformat()
    with Session(engine) as s:
        activas = s.exec(select(Workday).where(Workday.status == "active")).all()
        assert [w.date for w in activas] == [today]
        vieja = s.exec(select(Workday).where(Workday.date == "2020-01-01")).one()
        assert vieja.status == "closed"
        assert vieja.ended_at is not None

    # El dashboard refleja la jornada de hoy, no la vieja.
    assert client.get("/api/dashboard").json()["workday"]["date"] == today
