"""Hito 2: cost_today_usd (captured) y burn_rate_usd_per_hour (estimated)."""
from __future__ import annotations

import copy
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app
from app.models import AgentSession, UsageSnapshot
from app.services.usage import burn_rate_usd_per_hour, cost_today_usd

client = TestClient(app)


def test_cost_today_suma_el_maximo_por_sesion(raw_statusline: dict) -> None:
    init_db()
    # Sesión A: dos ticks; el costo es acumulado, debe contar solo el último (mayor).
    a1 = copy.deepcopy(raw_statusline)
    a1["cost"]["total_cost_usd"] = 0.50
    a1["context_window"]["used_percentage"] = 3
    client.post("/api/snapshots", json=a1)
    a2 = copy.deepcopy(raw_statusline)
    a2["cost"]["total_cost_usd"] = 1.20  # mismo session_id, costo acumulado mayor
    a2["context_window"]["used_percentage"] = 9  # cambia el contenido -> no dedup
    client.post("/api/snapshots", json=a2)

    # Sesión B: otra sesión del día.
    b = copy.deepcopy(raw_statusline)
    b["session_id"] = "bbbbbbbb-0000-0000-0000-000000000000"
    b["cost"]["total_cost_usd"] = 0.80
    client.post("/api/snapshots", json=b)

    d = client.get("/api/dashboard").json()
    # 1.20 (máx sesión A) + 0.80 (sesión B) = 2.00
    assert d["metrics"]["cost_today_usd"] == 2.0


def test_burn_rate_desde_duracion_de_sesion(raw_statusline: dict) -> None:
    init_db()
    raw = copy.deepcopy(raw_statusline)
    raw["cost"]["total_cost_usd"] = 1.0
    raw["cost"]["total_duration_ms"] = 1_800_000  # 0.5 h
    client.post("/api/snapshots", json=raw)

    d = client.get("/api/dashboard").json()
    assert d["metrics"]["burn_rate_usd_per_hour"] == 2.0  # 1.0 USD / 0.5 h


def test_burn_rate_none_si_duracion_insuficiente() -> None:
    # Unidad: duración por debajo del umbral -> None (no se inventa).
    snap = UsageSnapshot(
        workday_id="w",
        content_hash="h",
        cost_session_usd=0.5,
        session_duration_ms=10_000,  # 10 s < 60 s
    )
    assert burn_rate_usd_per_hour(snap, None, datetime.now(UTC)) is None


def test_burn_rate_fallback_a_started_at() -> None:
    # Sin session_duration_ms, usa el tiempo de pared desde started_at.
    started = datetime(2026, 6, 28, 10, 0, 0, tzinfo=UTC)
    now = datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC)  # 2 h
    snap = UsageSnapshot(workday_id="w", content_hash="h", cost_session_usd=3.0)
    sess = AgentSession(
        workday_id="w", session_external_id="x", started_at=started
    )
    assert burn_rate_usd_per_hour(snap, sess, now) == 1.5  # 3.0 / 2 h


def test_cost_today_none_sin_datos() -> None:
    init_db()
    from app.db import get_session

    db = next(get_session())
    try:
        assert cost_today_usd(db, "jornada-inexistente") is None
    finally:
        db.close()
