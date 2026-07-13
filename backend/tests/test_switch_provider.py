"""Recomendación advisory ``switch_provider``: sugiere cambiar al proveedor con más margen."""
from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import engine
from app.main import app
from app.models import UsageSnapshot, Workday

client = TestClient(app)


def _post_claude(base: dict, pct5: float, cost: float, pct7: float = 7) -> None:
    raw = copy.deepcopy(base)
    raw["rate_limits"]["five_hour"]["used_percentage"] = pct5
    raw["rate_limits"]["seven_day"]["used_percentage"] = pct7
    raw["cost"]["total_cost_usd"] = cost
    client.post("/api/snapshots", json=raw)


def _workday_id() -> str:
    with Session(engine) as db:
        wd = db.exec(select(Workday).where(Workday.status == "active")).first()
        assert wd is not None
        return wd.id


def _insert_codex(workday_id: str, five_h: float, minutes_ago: int = 2) -> None:
    with Session(engine) as db:
        db.add(
            UsageSnapshot(
                workday_id=workday_id,
                captured_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
                provider="codex",
                source_type="captured",
                source_name="codex_rollout",
                content_hash=f"codex-{five_h}-{minutes_ago}",
                rate_limit_5h_percentage=five_h,
                rate_limit_5h_resets_at=datetime.now(UTC) + timedelta(hours=3),
                rate_limit_7d_percentage=5,
                rate_limit_7d_resets_at=datetime.now(UTC) + timedelta(days=2),
            )
        )
        db.commit()


def _recs(rec_type: str | None = None) -> list[dict]:
    d = client.get("/api/dashboard").json()
    recs = d["recommendations"]
    return [r for r in recs if rec_type is None or r["recommendation_type"] == rec_type]


def test_recomienda_cambio_a_proveedor_con_mas_margen(raw_statusline: dict) -> None:
    _post_claude(raw_statusline, pct5=10, cost=1.0)  # green, abre jornada
    _insert_codex(_workday_id(), five_h=5)  # margen 95
    _post_claude(raw_statusline, pct5=85, cost=2.0)  # claude rojo (margen 15), activo

    switch = _recs("switch_provider")
    assert len(switch) == 1
    assert "Codex" in switch[0]["message"]
    d = client.get("/api/dashboard").json()
    assert d["active_provider"] == "claude"
    assert d["recommended_provider"] == "codex"


def test_no_recomienda_si_el_activo_va_bien(raw_statusline: dict) -> None:
    _post_claude(raw_statusline, pct5=10, cost=1.0)  # green
    _insert_codex(_workday_id(), five_h=90)  # codex peor, pero da igual
    _post_claude(raw_statusline, pct5=10, cost=2.0)  # sigue green
    assert _recs("switch_provider") == []


def test_no_recomienda_si_la_diferencia_es_marginal(raw_statusline: dict) -> None:
    _post_claude(raw_statusline, pct5=10, cost=1.0)
    _insert_codex(_workday_id(), five_h=40)  # margen 60
    _post_claude(raw_statusline, pct5=55, cost=2.0)  # yellow, margen 45; delta 15 < 20
    assert _recs("switch_provider") == []


def test_no_duplica_mismo_par(raw_statusline: dict) -> None:
    _post_claude(raw_statusline, pct5=10, cost=1.0)
    _insert_codex(_workday_id(), five_h=5)
    _post_claude(raw_statusline, pct5=85, cost=2.0)  # crea switch claude->codex
    _post_claude(raw_statusline, pct5=86, cost=3.0)  # sigue rojo, mismo par -> no duplica
    assert len(_recs("switch_provider")) == 1


def test_se_limpia_cuando_ya_no_aplica(raw_statusline: dict) -> None:
    _post_claude(raw_statusline, pct5=10, cost=1.0)
    _insert_codex(_workday_id(), five_h=5)
    _post_claude(raw_statusline, pct5=85, cost=2.0)  # switch activo
    assert len(_recs("switch_provider")) == 1
    _post_claude(raw_statusline, pct5=10, cost=3.0)  # vuelve a green -> se limpia
    assert _recs("switch_provider") == []


def test_coexiste_con_recomendacion_de_estado(raw_statusline: dict) -> None:
    _post_claude(raw_statusline, pct5=10, cost=1.0)
    _insert_codex(_workday_id(), five_h=5)
    _post_claude(raw_statusline, pct5=85, cost=2.0)  # rojo

    types = {r["recommendation_type"] for r in _recs()}
    assert "switch_provider" in types
    assert "reserve_for_critical" in types  # el flujo de estado sigue vivo en paralelo
