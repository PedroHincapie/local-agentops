"""Modelos SQLModel.

Hito 0: ``Workday`` y ``UsageSnapshot`` (núcleo).
Hito 1: ``Project`` y ``AgentSession`` (auto-detección de proyecto/sesión + métricas
manuales). Hito 4: ``Recommendation`` (motor de recomendaciones). El resto
(``usage_events``) se añade en hitos posteriores.

Multi-provider: la dimensión de proveedor vive como la columna ``UsageSnapshot.provider``
(claude | codex | gemini); NO hay tablas ``providers`` / ``provider_capabilities`` (no se
reintroduce un catálogo de providers, solo se etiqueta el origen de cada snapshot).
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


class Project(SQLModel, table=True):
    """Proyecto auto-detectado desde ``workspace.project_dir`` del statusline."""

    __tablename__ = "projects"

    id: str = Field(default_factory=_uuid, primary_key=True)
    name: str  # basename de repository_path
    repository_path: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class AgentSession(SQLModel, table=True):
    """Sesión de trabajo, auto-detectada por ``session_id`` de Claude Code.

    ``task_type`` y ``objective`` son los únicos campos ``manual`` (los anota el
    usuario vía ``PATCH /api/sessions/{id}``).
    """

    __tablename__ = "agent_sessions"

    id: str = Field(default_factory=_uuid, primary_key=True)
    workday_id: str = Field(foreign_key="workdays.id", index=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    session_external_id: str = Field(index=True, unique=True)  # session_id de Claude Code
    model: str | None = None
    git_branch: str | None = None  # derivado por git (no viene en el statusline)
    task_type: str | None = None  # manual
    objective: str | None = None  # manual
    started_at: datetime = Field(default_factory=_utcnow)
    ended_at: datetime | None = None
    status: str = "active"  # active | closed
    summary: str | None = None


class UsageSnapshot(SQLModel, table=True):
    __tablename__ = "usage_snapshots"

    id: str = Field(default_factory=_uuid, primary_key=True)
    workday_id: str = Field(foreign_key="workdays.id", index=True)
    session_id: str | None = Field(default=None, foreign_key="agent_sessions.id", index=True)
    captured_at: datetime = Field(default_factory=_utcnow, index=True)

    # Clasificación de origen (CLAUDE.md: nunca inventar valores).
    # provider  = la cuenta/suscripción (claude | codex | gemini).
    # source_name = el mecanismo de captura (statusline | ccusage | codex_rollout |
    #               gemini_otel | manual). Se separan a propósito: un proveedor puede
    #               tener varios mecanismos (Claude: statusline + ccusage).
    provider: str = "claude"
    source_type: str = "captured"  # official | captured | estimated | manual
    source_name: str = "statusline"  # statusline | ccusage | codex_rollout | gemini_otel | manual
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


class Recommendation(SQLModel, table=True):
    """Recomendación operativa generada por el motor (Hito 4).

    ``acknowledged_at`` cubre dos casos: el usuario la marcó como vista (ack), o fue
    superseded por un cambio de estado. "Activa" = ``acknowledged_at is None``.
    """

    __tablename__ = "recommendations"

    id: str = Field(default_factory=_uuid, primary_key=True)
    workday_id: str = Field(foreign_key="workdays.id", index=True)
    session_id: str | None = Field(default=None, foreign_key="agent_sessions.id", index=True)
    recommendation_type: str  # continue | reduce_context | reserve_for_critical | pause | ...
    severity: str  # info | warning | critical
    message: str
    reason: str | None = None
    created_at: datetime = Field(default_factory=_utcnow, index=True)
    acknowledged_at: datetime | None = None
