"""Acceso a SQLite vía SQLModel. Modo WAL, transacciones cortas en los servicios."""
from __future__ import annotations

import os
from collections.abc import Iterator

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


def init_db() -> None:
    """Crea las tablas si no existen (Alembic se difiere; ver plan, Hito 5)."""
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
