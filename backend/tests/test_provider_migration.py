"""Dimensión multi-provider: columna ``provider`` + migración aditiva idempotente."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import _column_exists, _run_additive_migrations, engine, init_db
from app.main import app
from app.models import UsageSnapshot

client = TestClient(app)


def test_provider_columna_existe_tras_init_db() -> None:
    init_db()
    with engine.begin() as conn:
        assert _column_exists(conn, "usage_snapshots", "provider")


def test_snapshot_statusline_es_claude_por_defecto(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)
    with Session(engine) as db:
        snap = db.exec(select(UsageSnapshot)).first()
    assert snap is not None
    assert snap.provider == "claude"  # default del modelo


def test_migracion_es_idempotente() -> None:
    init_db()
    # Correrla de nuevo no debe fallar ni duplicar la columna.
    _run_additive_migrations()
    _run_additive_migrations()
    with engine.begin() as conn:
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(usage_snapshots)").fetchall()]
    assert cols.count("provider") == 1


def test_migracion_repuebla_columna_en_tabla_legacy() -> None:
    """Simula una DB previa (sin ``provider``): la migración la añade con default 'claude'."""
    init_db()
    with engine.begin() as conn:
        # SQLite >=3.35 soporta DROP COLUMN; simula el esquema legacy.
        conn.exec_driver_sql("ALTER TABLE usage_snapshots DROP COLUMN provider")
        conn.exec_driver_sql(
            "INSERT INTO workdays (id, date, started_at, status) "
            "VALUES ('wd-1', '2026-01-01', '2026-01-01T00:00:00', 'closed')"
        )
        conn.exec_driver_sql(
            "INSERT INTO usage_snapshots "
            "(id, workday_id, captured_at, source_type, source_name, data_quality, content_hash) "
            "VALUES ('legacy-1', 'wd-1', '2026-01-01T00:00:00', "
            "'captured', 'statusline', 'ok', 'h1')"
        )
        assert not _column_exists(conn, "usage_snapshots", "provider")

    _run_additive_migrations()

    with engine.begin() as conn:
        assert _column_exists(conn, "usage_snapshots", "provider")
        val = conn.exec_driver_sql(
            "SELECT provider FROM usage_snapshots WHERE id='legacy-1'"
        ).fetchone()
    assert val[0] == "claude"  # backfill por el DEFAULT del DDL
