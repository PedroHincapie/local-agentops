"""Modelos SQLModel.

Hito 0: ``Workday`` y ``UsageSnapshot`` (núcleo). El esquema completo
(``projects``, ``agent_sessions``, ``usage_events``, ``recommendations``) se añade
en hitos posteriores. NO existen tablas ``providers`` / ``provider_capabilities``
(diseño multi-provider descartado en el MVP).
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlmodel import Field, SQLModel


def _uuid() -> str:
    return str(uuid4())


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Workday(SQLModel, table=True):
    __tablename__ = "workdays"

    id: str = Field(default_factory=_uuid, primary_key=True)
    date: str = Field(index=True, unique=True)  # fecha local ISO (YYYY-MM-DD)
    started_at: datetime = Field(default_factory=_utcnow)
    ended_at: datetime | None = None
    status: str = "active"  # active | closed | interrupted
    initial_state: str | None = None  # green|yellow|red|critical del primer snapshot
    current_state: str | None = None


class UsageSnapshot(SQLModel, table=True):
    __tablename__ = "usage_snapshots"

    id: str = Field(default_factory=_uuid, primary_key=True)
    workday_id: str = Field(foreign_key="workdays.id", index=True)
    captured_at: datetime = Field(default_factory=_utcnow, index=True)

    # Clasificación de origen (CLAUDE.md: nunca inventar valores).
    source_type: str = "captured"  # official | captured | estimated | manual
    source_name: str = "statusline"  # statusline | ccusage | manual
    data_quality: str = "ok"  # flag simple en Hito 0; JSON detallado en hitos siguientes

    # Dedup: hash de contenido del tick (CLAUDE.md / contrato §2).
    content_hash: str = Field(index=True)

    # --- Identidad de sesión / workspace (captured) ---
    session_external_id: str | None = Field(default=None, index=True)
    session_name: str | None = None
    transcript_path: str | None = None
    project_path: str | None = None
    current_dir: str | None = None

    # --- Modelo / CLI (captured) ---
    model_id: str | None = None
    model_name: str | None = None
    effort_level: str | None = None
    cli_version: str | None = None

    # --- Costo / actividad (captured; referencial en suscripción) ---
    cost_session_usd: float | None = None
    session_duration_ms: int | None = None
    lines_added: int | None = None
    lines_removed: int | None = None

    # --- Contexto (captured) ---
    context_window_size: int | None = None
    context_used_percentage: float | None = None
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None

    # --- Rate limits (official: métrica canónica) ---
    rate_limit_5h_percentage: float | None = None
    rate_limit_5h_resets_at: datetime | None = None
    rate_limit_7d_percentage: float | None = None
    rate_limit_7d_resets_at: datetime | None = None
