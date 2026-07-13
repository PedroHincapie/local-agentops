"""Hito 3: reconciliador ccusage (red de seguridad, no captura primaria)."""
from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.capture.base import CaptureError
from app.db import init_db
from app.main import app
from app.services.reconciler import reconcile_once
from app.services.reconciler_state import state

client = TestClient(app)


class _FakeSource:
    """CaptureSource de prueba: devuelve campos fijos o lanza un error."""

    name = "ccusage"
    provider = "claude"
    source_name = "ccusage"

    def __init__(self, fields: dict[str, Any] | None = None, error: Exception | None = None):
        self._fields = fields
        self._error = error

    def fetch(self) -> dict[str, Any] | None:
        if self._error is not None:
            raise self._error
        return self._fields


_CCUSAGE_FIELDS = {
    "model_id": "claude-opus-4-8",
    "model_name": "claude-opus-4-8",
    "cost_session_usd": 3.99,
    "total_input_tokens": 3136,
    "total_output_tokens": 39875,
    "cache_creation_input_tokens": 98515,
    "cache_read_input_tokens": 3993152,
    "rate_limit_5h_percentage": None,
    "rate_limit_7d_percentage": None,
}


def test_reconcile_sin_jornada_no_hace_nada() -> None:
    init_db()
    result = reconcile_once(_FakeSource(_CCUSAGE_FIELDS))
    assert result["reconciled"] is False
    assert result["reason"] == "sin jornada activa"


def test_reconcile_persiste_snapshot_ccusage_sin_corromper_el_feed(raw_statusline: dict) -> None:
    init_db()
    # Abre jornada con un tick statusline (green).
    client.post("/api/snapshots", json=raw_statusline)

    result = reconcile_once(_FakeSource(_CCUSAGE_FIELDS))
    assert result["reconciled"] is True
    assert result["snapshot_id"]

    d = client.get("/api/dashboard").json()
    # El status y las ventanas siguen viniendo del statusline (no se degradan a critical).
    assert d["status"] == "green"
    assert d["metrics"]["five_hour"]["used_percentage"] == 45
    # cost_today NO incluye el costo del bloque ccusage (otra base contable).
    assert d["metrics"]["cost_today_usd"] == round(raw_statusline["cost"]["total_cost_usd"], 6)


def test_reconcile_dedup_sin_cambios(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)
    source = _FakeSource(_CCUSAGE_FIELDS)
    assert reconcile_once(source)["reconciled"] is True
    second = reconcile_once(source)
    assert second["reconciled"] is False
    assert second["reason"] == "sin cambios"


def test_reconcile_error_de_captura_se_registra(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)
    result = reconcile_once(_FakeSource(error=CaptureError("ccusage no disponible")))
    assert result["reconciled"] is False
    assert result["reason"] == "error de captura"
    assert state.healthy is False
    assert "ccusage no disponible" in (state.last_error or "")
