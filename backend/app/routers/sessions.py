"""``GET /api/sessions/current`` y ``PATCH /api/sessions/{id}`` (contrato §4.3–4.4)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.db import get_session
from app.services import sessions as sessions_service

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class SessionAnnotation(BaseModel):
    """Métricas ``manual``: lo único que el usuario ingresa a mano (§4.4)."""

    objective: str | None = None
    task_type: str | None = None


@router.get("/current")
def get_current_session(db: Session = Depends(get_session)) -> dict:
    agent_session = sessions_service.current_session(db)
    if agent_session is None:
        raise HTTPException(status_code=404, detail="No hay sesión activa")
    return sessions_service.build_session_view(db, agent_session)


@router.get("/current/large-files")
def get_current_large_files(db: Session = Depends(get_session)) -> dict:
    agent_session = sessions_service.current_session(db)
    if agent_session is None:
        raise HTTPException(status_code=404, detail="No hay sesión activa")

    # Obtener el path del proyecto desde el snapshot más reciente
    snap = sessions_service._latest_snapshot(db, agent_session)
    path = snap.project_path if snap else None

    # Escanea y devuelve los 5 archivos más pesados del proyecto
    files = sessions_service.get_large_files(path, limit=5)
    return {"files": files}


@router.patch("/{session_id}")
async def patch_session(
    session_id: str,
    annotation: SessionAnnotation,
    db: Session = Depends(get_session),
) -> dict:
    agent_session = sessions_service.get_session_by_id(db, session_id)
    if agent_session is None:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    # PATCH parcial: solo se tocan los campos enviados explícitamente.
    data = annotation.model_dump(exclude_unset=True)
    if "objective" in data:
        agent_session.objective = data["objective"]
    if "task_type" in data:
        agent_session.task_type = data["task_type"]
    db.add(agent_session)
    db.commit()
    db.refresh(agent_session)

    # Transmite la actualización en tiempo real del dashboard
    try:
        from app.services.dashboard import build_dashboard
        from app.services.websocket import manager
        db_data = build_dashboard(db)
        await manager.broadcast(db_data)
    except Exception:
        pass

    return sessions_service.build_session_view(db, agent_session)
