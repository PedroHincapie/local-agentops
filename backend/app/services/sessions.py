"""Auto-detección de proyecto/sesión y vista de la sesión activa.

- ``projects`` se detectan desde ``workspace.project_dir`` (basename = nombre).
- ``agent_sessions`` se detectan desde ``session_id`` de Claude Code; al cambiar de
  ``session_external_id`` se cierra la sesión activa anterior (contrato §6).
- ``git_branch`` no viene en el statusline: se deriva con ``git rev-parse`` y se
  cachea por ruta de proyecto (CLAUDE.md / contrato §6).

``task_type`` y ``objective`` son las únicas métricas ``manual``.
"""
from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, func, select

from app.config import settings
from app.models import AgentSession, Project, UsageSnapshot, Workday

# Cache de rama por ruta de proyecto: evita invocar git en cada tick.
_git_branch_cache: dict[str, str | None] = {}


def _basename(path: str | None) -> str | None:
    if not path:
        return None
    return path.rstrip("/").rsplit("/", 1)[-1]


def derive_git_branch(project_path: str | None) -> str | None:
    """Rama Git actual del proyecto, o None si no aplica. Cacheada por ruta."""
    if not project_path:
        return None
    if project_path in _git_branch_cache:
        return _git_branch_cache[project_path]
    branch: str | None
    try:
        result = subprocess.run(
            ["git", "-C", project_path, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        branch = result.stdout.strip() if result.returncode == 0 else None
        if branch in ("", "HEAD"):  # repo vacío o detached HEAD
            branch = None
    except (OSError, subprocess.SubprocessError):
        branch = None
    _git_branch_cache[project_path] = branch
    return branch


def get_or_create_project(db: Session, project_path: str | None) -> Project | None:
    if not project_path:
        return None
    project = db.exec(
        select(Project).where(Project.repository_path == project_path)
    ).first()
    if project is None:
        project = Project(
            name=_basename(project_path) or project_path,
            repository_path=project_path,
        )
        db.add(project)
        db.flush()
    else:
        project.updated_at = datetime.now(UTC)
        db.add(project)
    return project


def get_or_create_session(
    db: Session, workday: Workday, fields: dict[str, Any]
) -> AgentSession | None:
    """Devuelve la sesión activa para este tick, creándola si es nueva.

    Al detectar un ``session_external_id`` nuevo, cierra las demás sesiones activas
    de la jornada (cambio de sesión = cierre de la anterior).
    """
    external_id = fields.get("session_external_id")
    if not external_id:
        return None

    existing = db.exec(
        select(AgentSession).where(AgentSession.session_external_id == external_id)
    ).first()
    if existing is not None:
        # Mantener el modelo al día (puede cambiar dentro de una sesión).
        model = fields.get("model_name")
        if model and existing.model != model:
            existing.model = model
            db.add(existing)
        return existing

    # Sesión nueva: cerrar las activas anteriores de la jornada.
    _close_active_sessions(db, workday.id, keep_external_id=external_id)

    project = get_or_create_project(db, fields.get("project_path"))
    agent_session = AgentSession(
        workday_id=workday.id,
        project_id=project.id if project else None,
        session_external_id=external_id,
        model=fields.get("model_name"),
        git_branch=derive_git_branch(fields.get("project_path")),
        started_at=datetime.now(UTC),
        status="active",
    )
    db.add(agent_session)
    db.flush()
    return agent_session


def _close_active_sessions(db: Session, workday_id: str, keep_external_id: str) -> None:
    actives = db.exec(
        select(AgentSession).where(
            AgentSession.workday_id == workday_id,
            AgentSession.status == "active",
            AgentSession.session_external_id != keep_external_id,
        )
    ).all()
    for s in actives:
        s.status = "closed"
        s.ended_at = datetime.now(UTC)
        db.add(s)


def _idle_seconds(snap: UsageSnapshot | None, now: datetime) -> float | None:
    """Segundos desde el último snapshot de la sesión, o None si no hay snapshot."""
    if snap is None:
        return None
    captured_at = (
        snap.captured_at
        if snap.captured_at.tzinfo
        else snap.captured_at.replace(tzinfo=UTC)
    )
    return (now - captured_at).total_seconds()


def close_idle_sessions(db: Session, now: datetime | None = None) -> int:
    """Cierra TODAS las sesiones activas sin snapshots recientes. Devuelve cuántas cerró.

    Barrido proactivo: lo invoca el reconciliador cada N min para que las sesiones se
    cierren aunque nadie consulte ``/api/sessions/current`` (el front no lo hace).
    """
    now = now or datetime.now(UTC)
    threshold = settings.session_idle_minutes * 60
    actives = db.exec(
        select(AgentSession).where(AgentSession.status == "active")
    ).all()
    closed = 0
    for s in actives:
        snap = _latest_snapshot(db, s)
        idle = _idle_seconds(snap, now)
        if idle is not None and idle > threshold:
            s.status = "closed"
            s.ended_at = snap.captured_at  # type: ignore[union-attr]  # snap no es None si idle no es None
            db.add(s)
            closed += 1
    if closed:
        db.commit()
    return closed


def current_session(db: Session) -> AgentSession | None:
    """Sesión activa más reciente (la de los últimos snapshots)."""
    active = db.exec(
        select(AgentSession)
        .where(AgentSession.status == "active")
        .order_by(AgentSession.started_at.desc())  # type: ignore[attr-defined]
    ).first()
    if active is None:
        return None

    # Cierre perezoso: si no hay actividad en el umbral configurado, cerrar y no devolverla.
    snap = _latest_snapshot(db, active)
    idle = _idle_seconds(snap, datetime.now(UTC))
    if idle is not None and idle > settings.session_idle_minutes * 60:
        active.status = "closed"
        active.ended_at = snap.captured_at  # type: ignore[union-attr]  # snap no es None si idle no es None
        db.add(active)
        db.commit()
        return None

    return active


def get_session_by_id(db: Session, session_id: str) -> AgentSession | None:
    """Busca por ``session_external_id`` (lo que ve el front) o por id interno."""
    found = db.exec(
        select(AgentSession).where(AgentSession.session_external_id == session_id)
    ).first()
    if found is not None:
        return found
    return db.get(AgentSession, session_id)


def _latest_snapshot(db: Session, agent_session: AgentSession) -> UsageSnapshot | None:
    return db.exec(
        select(UsageSnapshot)
        .where(UsageSnapshot.session_id == agent_session.id)
        .order_by(UsageSnapshot.captured_at.desc())  # type: ignore[attr-defined]
    ).first()


def _isoformat(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_session_view(db: Session, agent_session: AgentSession) -> dict[str, Any]:
    """Vista del contrato §4.3 (la misma que devuelve PATCH §4.4)."""
    project = (
        db.get(Project, agent_session.project_id) if agent_session.project_id else None
    )
    snap = _latest_snapshot(db, agent_session)
    snapshot_count = db.exec(
        select(func.count())
        .select_from(UsageSnapshot)
        .where(UsageSnapshot.session_id == agent_session.id)
    ).one()
    return {
        "id": agent_session.session_external_id,
        "session_name": snap.session_name if snap else None,
        "project_name": project.name if project else None,
        "model_name": agent_session.model,
        "git_branch": agent_session.git_branch,
        "task_type": agent_session.task_type,
        "objective": agent_session.objective,
        "status": agent_session.status,
        "started_at": _isoformat(agent_session.started_at),
        "ended_at": _isoformat(agent_session.ended_at),
        "snapshot_count": snapshot_count,
        "cost_session_usd": snap.cost_session_usd if snap else None,
    }


# Ruido de build/entorno: NO son "archivos del trabajo" del usuario, así que se
# excluyen del escaneo de archivos pesados (código/docs es lo que interesa).
_LARGE_FILES_EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "node_modules",
    "dist",
    "build",
    "data",  # base SQLite local (WAL/SHM)
    ".claude",
}
_LARGE_FILES_EXCLUDE_SUFFIXES = (".db", ".db-wal", ".db-shm", ".pyc")


def get_large_files(directory_path: str | None, limit: int = 5) -> list[dict[str, Any]]:
    import os

    if not directory_path or not os.path.isdir(directory_path):
        return []

    file_list: list[dict[str, Any]] = []
    try:
        for root, dirs, files in os.walk(directory_path):
            # Poda in-place: no descender en directorios de build/entorno.
            dirs[:] = [d for d in dirs if d not in _LARGE_FILES_EXCLUDE_DIRS]
            for file in files:
                if file.endswith(_LARGE_FILES_EXCLUDE_SUFFIXES):
                    continue
                filepath = os.path.join(root, file)
                try:
                    if os.path.islink(filepath):
                        continue
                    size = os.path.getsize(filepath)
                    rel_path = os.path.relpath(filepath, directory_path)
                    file_list.append(
                        {
                            "path": rel_path,
                            "size_bytes": size,
                            "size_kb": round(size / 1024, 1),
                        }
                    )
                except OSError:
                    continue
    except Exception:
        return []

    file_list.sort(key=lambda x: x["size_bytes"], reverse=True)
    return file_list[:limit]
