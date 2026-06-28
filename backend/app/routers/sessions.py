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


@router.patch("/{session_id}")
def patch_session(
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
    return sessions_service.build_session_view(db, agent_session)
