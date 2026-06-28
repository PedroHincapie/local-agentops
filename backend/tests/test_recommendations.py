"""Hito 4: motor de recomendaciones (estado -> recomendación, ciclo de vida, API)."""
from __future__ import annotations

import copy

from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app

client = TestClient(app)


def _with_window(raw: dict, five_hour_pct: float) -> dict:
    out = copy.deepcopy(raw)
    out["rate_limits"]["five_hour"]["used_percentage"] = five_hour_pct
    return out


def test_green_genera_continue(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)  # 5h=45 -> green

    recs = client.get("/api/recommendations").json()["recommendations"]
    assert len(recs) == 1
    assert recs[0]["recommendation_type"] == "continue"
    assert recs[0]["severity"] == "info"
    assert recs[0]["reason"] == "Ventana de 5h al 45%, 7d al 7%."
    assert recs[0]["acknowledged_at"] is None

    # También aparece en el dashboard (forma abreviada).
    d = client.get("/api/dashboard").json()
    assert len(d["recommendations"]) == 1
    assert d["recommendations"][0]["recommendation_type"] == "continue"
    assert "workday_id" not in d["recommendations"][0]  # forma breve


def test_no_spam_en_el_mismo_estado(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=_with_window(raw_statusline, 45))  # green
    client.post("/api/snapshots", json=_with_window(raw_statusline, 10))  # sigue green

    recs = client.get("/api/recommendations").json()["recommendations"]
    assert len(recs) == 1  # no se duplica tick a tick


def test_cambio_de_estado_supersede_la_anterior(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=_with_window(raw_statusline, 45))  # green
    client.post("/api/snapshots", json=_with_window(raw_statusline, 90))  # red

    recs = client.get("/api/recommendations").json()["recommendations"]
    assert len(recs) == 1  # la 'continue' quedó superseded
    assert recs[0]["recommendation_type"] == "reserve_for_critical"
    assert recs[0]["severity"] == "warning"


def test_ack_marca_como_vista(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)
    rec_id = client.get("/api/recommendations").json()["recommendations"][0]["id"]

    acked = client.post(f"/api/recommendations/{rec_id}/ack")
    assert acked.status_code == 200
    assert acked.json()["acknowledged_at"] is not None

    # Ya no está activa.
    assert client.get("/api/recommendations").json()["recommendations"] == []
    assert client.get("/api/dashboard").json()["recommendations"] == []


def test_ack_inexistente_da_404() -> None:
    init_db()
    assert client.post("/api/recommendations/no-existe/ack").status_code == 404


def test_critical_sin_rate_limits_recomienda_pause() -> None:
    init_db()
    client.post("/api/snapshots", content=b"")  # sin rate_limits -> critical

    recs = client.get("/api/recommendations").json()["recommendations"]
    assert len(recs) == 1
    assert recs[0]["recommendation_type"] == "pause"
    assert recs[0]["severity"] == "critical"
    assert recs[0]["reason"] == "Sin datos de rate_limits."
