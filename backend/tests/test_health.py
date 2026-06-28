"""Endpoint /api/health (§4.8)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app

client = TestClient(app)


def test_health_sin_actividad() -> None:
    init_db()
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["uptime_seconds"] >= 0
    assert body["sources"]["statusline_hook"]["healthy"] is False
    assert body["sources"]["statusline_hook"]["last_received_at"] is None
    assert body["scheduler"]["interval_seconds"] == 300


def test_health_tras_recibir_statusline(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)

    body = client.get("/api/health").json()
    assert body["sources"]["statusline_hook"]["healthy"] is True
    assert body["sources"]["statusline_hook"]["last_received_at"] is not None
