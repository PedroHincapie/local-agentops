from __future__ import annotations

import copy

from app.normalizer import content_hash, normalize


def test_mapea_campos_clave(raw_statusline: dict) -> None:
    n = normalize(raw_statusline)
    assert n["session_external_id"] == "623a283b-7b38-4c89-913e-4b95e490a0c1"
    assert n["model_name"] == "Opus 4.8"
    assert n["project_path"].endswith("proyecto-agentOps")
    assert n["rate_limit_5h_percentage"] == 45
    assert n["rate_limit_7d_percentage"] == 7
    assert n["cache_read_input_tokens"] == 30323


def test_epoch_resets_se_convierte_a_utc(raw_statusline: dict) -> None:
    n = normalize(raw_statusline)
    assert n["rate_limit_5h_resets_at"].isoformat() == "2026-06-27T17:00:00+00:00"


def test_tolera_campos_faltantes_y_current_usage_null() -> None:
    n = normalize({"session_id": "x", "context_window": {"current_usage": None}})
    assert n["session_external_id"] == "x"
    assert n["cache_read_input_tokens"] is None
    assert n["rate_limit_5h_percentage"] is None


def test_hash_estable_y_sensible_al_contenido(raw_statusline: dict) -> None:
    a = content_hash(raw_statusline)
    assert a == content_hash(copy.deepcopy(raw_statusline))
    changed = copy.deepcopy(raw_statusline)
    changed["rate_limits"]["five_hour"]["used_percentage"] = 46
    assert content_hash(changed) != a
