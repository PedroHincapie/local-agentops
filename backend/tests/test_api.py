from __future__ import annotations

from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app

client = TestClient(app)


def test_walking_skeleton_end_to_end(raw_statusline: dict) -> None:
    init_db()

    # 1) Ingesta: primer tick -> 202, no deduplicado, jornada abierta.
    r1 = client.post("/api/snapshots", json=raw_statusline)
    assert r1.status_code == 202
    body1 = r1.json()
    assert body1["accepted"] is True
    assert body1["deduplicated"] is False
    assert body1["snapshot_id"]
    assert body1["status"] == "green"

    # 2) Mismo tick otra vez -> deduplicado, sin nuevo snapshot.
    r2 = client.post("/api/snapshots", json=raw_statusline)
    body2 = r2.json()
    assert body2["deduplicated"] is True
    assert body2["snapshot_id"] is None

    # 3) Dashboard refleja el estado real del contrato.
    d = client.get("/api/dashboard").json()
    assert d["status"] == "green"
    assert d["metrics"]["five_hour"]["used_percentage"] == 45
    assert d["metrics"]["five_hour"]["data_quality"] == "official"
    assert d["metrics"]["context"]["remaining_percentage"] == 97
    assert d["current_session"]["model_name"] == "Opus 4.8"


def test_snapshots_tolera_body_vacio() -> None:
    init_db()
    r = client.post("/api/snapshots", content=b"")
    assert r.status_code == 202
    assert r.json()["status"] == "critical"  # sin rate_limits -> critical
