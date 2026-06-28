"""Endpoints de reportes: /api/usage/today (§4.5) y /api/usage/history (§4.6)."""
from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app

client = TestClient(app)


def test_usage_today(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)
    client.patch(
        f"/api/sessions/{raw_statusline['session_id']}",
        json={"task_type": "documentación"},
    )

    body = client.get("/api/usage/today").json()
    assert body["status"] == "green"
    assert body["cost_today_usd"] == round(raw_statusline["cost"]["total_cost_usd"], 6)
    assert body["peak_five_hour_percentage"] == 45
    assert body["peak_seven_day_percentage"] == 7
    assert body["totals"]["total_input_tokens"] == 32371
    assert body["totals"]["total_output_tokens"] == 464
    assert body["totals"]["snapshots"] == 1
    assert body["totals"]["sessions"] == 1
    assert body["by_project"] == [
        {"project_name": "proyecto-agentOps", "cost_usd": 0.365536, "sessions": 1}
    ]
    assert body["by_task_type"] == [{"task_type": "documentación", "cost_usd": 0.365536}]
    assert body["last_snapshot_at"] is not None


def test_usage_today_sin_jornada() -> None:
    init_db()
    body = client.get("/api/usage/today").json()
    assert body["workday_id"] is None
    assert body["status"] == "critical"
    assert body["totals"]["sessions"] == 0
    assert body["by_project"] == []


def test_usage_history_day(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)

    body = client.get("/api/usage/history?granularity=day").json()
    assert body["granularity"] == "day"
    assert len(body["series"]) == 1
    entry = body["series"][0]
    assert entry["period"] == datetime.now().date().isoformat()
    assert entry["cost_usd"] == round(raw_statusline["cost"]["total_cost_usd"], 6)
    assert entry["peak_five_hour_percentage"] == 45
    assert entry["sessions"] == 1


def test_usage_history_filtro_proyecto(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)

    hit = client.get("/api/usage/history?project=proyecto-agentOps").json()
    assert len(hit["series"]) == 1

    miss = client.get("/api/usage/history?project=no-existe").json()
    assert miss["series"] == []


def test_usage_history_granularity_month(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)

    body = client.get("/api/usage/history?granularity=month").json()
    assert body["series"][0]["period"] == datetime.now().date().isoformat()[:7]
