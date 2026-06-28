"""Hito 3: CcusageSource mapea la salida real de ccusage (runner inyectado)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.capture.base import CaptureError
from app.capture.ccusage import CcusageSource

FIXTURES = Path(__file__).parent / "fixtures"
BLOCKS_JSON = (FIXTURES / "ccusage_blocks.json").read_text()


def _runner_returning(text: str):
    return lambda _args: text


def test_mapea_bloque_activo() -> None:
    src = CcusageSource(runner=_runner_returning(BLOCKS_JSON))
    fields = src.fetch()
    assert fields is not None
    assert fields["cost_session_usd"] == 3.994281
    assert fields["model_name"] == "claude-opus-4-8"
    assert fields["total_input_tokens"] == 3136
    assert fields["total_output_tokens"] == 39875
    assert fields["cache_creation_input_tokens"] == 98515
    assert fields["cache_read_input_tokens"] == 3993152
    # ccusage no aporta rate_limits oficiales.
    assert fields["rate_limit_5h_percentage"] is None
    assert fields["rate_limit_7d_percentage"] is None


def test_sin_bloques_devuelve_none() -> None:
    src = CcusageSource(runner=_runner_returning(json.dumps({"blocks": []})))
    assert src.fetch() is None


def test_json_invalido_lanza_capture_error() -> None:
    src = CcusageSource(runner=_runner_returning("no soy json"))
    with pytest.raises(CaptureError):
        src.fetch()


def test_toma_el_bloque_activo_entre_varios() -> None:
    payload = json.dumps(
        {
            "blocks": [
                {"isActive": False, "costUSD": 1.0, "models": ["x"], "tokenCounts": {}},
                {
                    "isActive": True,
                    "costUSD": 2.0,
                    "models": ["claude-opus-4-8"],
                    "tokenCounts": {},
                },
            ]
        }
    )
    src = CcusageSource(runner=_runner_returning(payload))
    fields = src.fetch()
    assert fields is not None
    assert fields["cost_session_usd"] == 2.0
