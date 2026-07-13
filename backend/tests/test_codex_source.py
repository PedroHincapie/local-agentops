"""Fuente Codex: parseo de rollout-*.jsonl (mapeo por window_minutes, tolerante a null)."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.capture.codex import CodexSource
from app.db import engine, init_db
from app.main import app
from app.models import UsageSnapshot
from app.services.reconciler import reconcile_once

client = TestClient(app)


def _write_rollout(dir_path: Path, name: str, lines: list[dict]) -> None:
    day = dir_path / "2026" / "07" / "13"
    day.mkdir(parents=True, exist_ok=True)
    (day / name).write_text("\n".join(json.dumps(o) for o in lines), encoding="utf-8")


def _rl(primary: dict | None, secondary: dict | None, usage: dict | None) -> dict:
    """Línea con los marcadores de uso/límites, anidados como en un rollout real."""
    return {
        "type": "event_msg",
        "payload": {
            "rate_limits": {"primary": primary, "secondary": secondary, "plan_type": "plus"},
            "total_token_usage": usage,
            "model_context_window": 258400,
        },
    }


_PRIMARY_7D = {"used_percent": 32.0, "window_minutes": 10080, "resets_at": 1784554415}
_SECONDARY_5H = {"used_percent": 12.0, "window_minutes": 300, "resets_at": 1784500000}
_USAGE = {
    "input_tokens": 1000,
    "cached_input_tokens": 800,
    "output_tokens": 50,
    "total_tokens": 1050,
}


def test_codex_mapea_ventanas_por_window_minutes(tmp_path: Path) -> None:
    # conversación (sin marcadores) que debe ignorarse + el evento de uso.
    _write_rollout(
        tmp_path,
        "rollout-a.jsonl",
        [
            {"type": "response_item", "payload": {"role": "user"}},
            _rl(_PRIMARY_7D, _SECONDARY_5H, _USAGE),
        ],
    )
    fields = CodexSource(sessions_dir=str(tmp_path)).fetch()
    assert fields is not None
    # primary=10080min -> 7d ; secondary=300min -> 5h (NO posicional).
    assert fields["rate_limit_5h_percentage"] == 12.0
    assert fields["rate_limit_7d_percentage"] == 32.0
    assert fields["rate_limit_5h_resets_at"] is not None
    assert fields["total_input_tokens"] == 1000
    assert fields["cache_read_input_tokens"] == 800
    assert fields["context_window_size"] == 258400


def test_codex_ultimo_rate_limits_gana(tmp_path: Path) -> None:
    older = _rl({"used_percent": 5.0, "window_minutes": 300, "resets_at": 1}, None, _USAGE)
    newer = _rl({"used_percent": 88.0, "window_minutes": 300, "resets_at": 2}, None, _USAGE)
    _write_rollout(tmp_path, "rollout-a.jsonl", [older, newer])
    fields = CodexSource(sessions_dir=str(tmp_path)).fetch()
    assert fields is not None
    assert fields["rate_limit_5h_percentage"] == 88.0  # el último


def test_codex_rate_limits_null_degrada(tmp_path: Path) -> None:
    """Bug conocido: rate_limits null. Se degradan las ventanas, no se inventan."""
    line = {
        "type": "event_msg",
        "payload": {"rate_limits": None, "total_token_usage": _USAGE},
    }
    _write_rollout(tmp_path, "rollout-a.jsonl", [line])
    fields = CodexSource(sessions_dir=str(tmp_path)).fetch()
    assert fields is not None
    assert fields["rate_limit_5h_percentage"] is None
    assert fields["rate_limit_7d_percentage"] is None
    assert fields["total_input_tokens"] == 1000  # los tokens sí se capturan


def test_codex_sin_rollouts_devuelve_none(tmp_path: Path) -> None:
    assert CodexSource(sessions_dir=str(tmp_path)).fetch() is None


def test_reconcile_codex_persiste_snapshot(tmp_path: Path, raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)  # abre jornada (claude)
    _write_rollout(tmp_path, "rollout-a.jsonl", [_rl(_PRIMARY_7D, _SECONDARY_5H, _USAGE)])

    result = reconcile_once(CodexSource(sessions_dir=str(tmp_path)))
    assert result["reconciled"] is True

    with Session(engine) as db:
        snap = db.exec(
            select(UsageSnapshot).where(UsageSnapshot.source_name == "codex_rollout")
        ).first()
    assert snap is not None
    assert snap.provider == "codex"
    assert snap.rate_limit_5h_percentage == 12.0

    # El dashboard muestra a Codex como proveedor, lado a lado con Claude.
    d = client.get("/api/dashboard").json()
    provs = {p["provider"] for p in d["providers"]}
    assert provs == {"claude", "codex"}
