"""Acceso a SQLite vía SQLModel. Modo WAL, transacciones cortas en los servicios."""
from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings


def _make_engine() -> Engine:
    # Para SQLite local, garantizar que el directorio del archivo exista.
    if settings.db_url.startswith("sqlite:///"):
        path = settings.db_url.replace("sqlite:///", "", 1)
        if path not in ("", ":memory:"):
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    return create_engine(
        settings.db_url,
        connect_args={"check_same_thread": False},
    )


engine = _make_engine()


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record):  # type: ignore[no-untyped-def]
    """WAL + foreign keys en cada conexión SQLite."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _column_exists(conn: Any, table: str, column: str) -> bool:
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)


def _run_additive_migrations() -> None:
    """Migraciones aditivas idempotentes (SQLModel ``create_all`` no altera tablas).

    Solo columnas nuevas con DEFAULT (no destructivas). Alembic se difiere; ver plan.
    """
    migrations: list[tuple[str, str, str]] = [
        # (tabla, columna, DDL) — provider: dimensión multi-provider; histórico = 'claude'.
        (
            "usage_snapshots",
            "provider",
            "ALTER TABLE usage_snapshots ADD COLUMN provider TEXT NOT NULL DEFAULT 'claude'",
        ),
    ]
    with engine.begin() as conn:
        for table, column, ddl in migrations:
            if not _column_exists(conn, table, column):
                conn.exec_driver_sql(ddl)


def init_db() -> None:
    """Crea las tablas si no existen y aplica migraciones aditivas (Alembic se difiere)."""
    SQLModel.metadata.create_all(engine)
    _run_additive_migrations()


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
