"""Hito 1: auto-detección de proyecto/sesión y métricas manuales."""
from __future__ import annotations

import copy

from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app

client = TestClient(app)


def test_sesion_se_autodetecta_y_aparece_en_dashboard(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)

    d = client.get("/api/dashboard").json()
    cs = d["current_session"]
    assert cs["id"] == raw_statusline["session_id"]
    assert cs["project_name"] == "proyecto-agentOps"
    assert cs["model_name"] == "Opus 4.8"
    # git_branch se deriva del repo real del proyecto (rama actual del checkout).
    assert cs["git_branch"]  # no None: estamos en un repo git
    # Métricas manuales aún sin anotar.
    assert cs["task_type"] is None
    assert cs["objective"] is None
    assert cs["started_at"] is not None


def test_sessions_current_endpoint(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)

    r = client.get("/api/sessions/current")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == raw_statusline["session_id"]
    assert body["status"] == "active"
    assert body["snapshot_count"] == 1
    assert body["cost_session_usd"] == raw_statusline["cost"]["total_cost_usd"]


def test_patch_anota_objetivo_y_tipo_de_tarea(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)
    sid = raw_statusline["session_id"]

    r = client.patch(
        f"/api/sessions/{sid}",
        json={"objective": "Documentar el enrolamiento", "task_type": "documentación"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["objective"] == "Documentar el enrolamiento"
    assert body["task_type"] == "documentación"

    # La anotación se refleja en el dashboard.
    cs = client.get("/api/dashboard").json()["current_session"]
    assert cs["task_type"] == "documentación"
    assert cs["objective"] == "Documentar el enrolamiento"


def test_cambio_de_sesion_cierra_la_anterior(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)

    other = copy.deepcopy(raw_statusline)
    other["session_id"] = "11111111-2222-3333-4444-555555555555"
    other["cost"]["total_cost_usd"] = 0.99
    client.post("/api/snapshots", json=other)

    # current = la nueva; la anterior queda cerrada (no es "current").
    current = client.get("/api/sessions/current").json()
    assert current["id"] == other["session_id"]


def test_patch_sesion_inexistente_da_404() -> None:
    init_db()
    r = client.patch("/api/sessions/no-existe", json={"objective": "x"})
    assert r.status_code == 404
