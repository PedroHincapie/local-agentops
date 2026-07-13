"""Dashboard multi-provider: providers[] con métricas nativas + recommended_provider.

Codex/Gemini se modelan SIN sesión (Camino A): snapshots primarios tagueados por
provider. Aquí se simula un feed Codex insertando su snapshot directamente.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import engine, init_db
from app.main import app
from app.models import UsageSnapshot, Workday

client = TestClient(app)


def _active_workday_id() -> str:
    with Session(engine) as db:
        wd = db.exec(select(Workday).where(Workday.status == "active")).first()
        assert wd is not None
        return wd.id


def _insert_codex_primary(workday_id: str, five_h: float, seven_d: float, minutes_ago: int) -> None:
    """Inserta un snapshot primario de Codex (source_name=codex_rollout), sin sesión."""
    with Session(engine) as db:
        db.add(
            UsageSnapshot(
                workday_id=workday_id,
                captured_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
                provider="codex",
                source_type="official",
                source_name="codex_rollout",
                content_hash=f"codex-{five_h}-{seven_d}-{minutes_ago}",
                model_id="gpt-5.5",
                model_name="gpt-5.5",
                rate_limit_5h_percentage=five_h,
                rate_limit_5h_resets_at=datetime.now(UTC) + timedelta(hours=3),
                rate_limit_7d_percentage=seven_d,
                rate_limit_7d_resets_at=datetime.now(UTC) + timedelta(days=2),
            )
        )
        db.commit()


def test_dashboard_solo_claude(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)
    d = client.get("/api/dashboard").json()

    assert [p["provider"] for p in d["providers"]] == ["claude"]
    assert d["active_provider"] == "claude"
    assert d["recommended_provider"] == "claude"
    assert d["providers"][0]["five_hour"]["used_percentage"] == 45


def test_dashboard_claude_y_codex_lado_a_lado(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)  # claude 5h=45 (más reciente)
    _insert_codex_primary(_active_workday_id(), five_h=90, seven_d=10, minutes_ago=2)

    d = client.get("/api/dashboard").json()

    provs = {p["provider"]: p for p in d["providers"]}
    assert set(provs) == {"claude", "codex"}
    # Métricas nativas de cada uno, lado a lado.
    assert provs["claude"]["five_hour"]["used_percentage"] == 45
    assert provs["codex"]["five_hour"]["used_percentage"] == 90
    assert provs["codex"]["status"] == "red"  # peak 90 -> [80,95) -> red
    # El proveedor activo es el del snapshot primario más reciente (claude).
    assert d["active_provider"] == "claude"
    # Recomienda el de mayor margen: claude (55) sobre codex (10).
    assert d["recommended_provider"] == "claude"
    # El top-level sigue reflejando al proveedor activo (claude, green).
    assert d["status"] == "green"


def test_recommended_provider_apunta_al_de_mas_margen(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)  # claude 5h=45 -> margen 55
    _insert_codex_primary(_active_workday_id(), five_h=5, seven_d=2, minutes_ago=2)  # margen 95

    d = client.get("/api/dashboard").json()

    assert d["active_provider"] == "claude"  # activo por recencia
    assert d["recommended_provider"] == "codex"  # pero conviene cambiar a codex
