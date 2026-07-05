"""``GET /api/recommendations`` y ``POST /api/recommendations/{id}/ack`` (§4.7)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models import Recommendation
from app.services import recommendations as rec_service

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


@router.get("")
def list_recommendations(db: Session = Depends(get_session)) -> dict:
    """Recomendaciones activas (no vistas/superseded), más recientes primero."""
    recs = db.exec(
        select(Recommendation)
        .where(Recommendation.acknowledged_at.is_(None))  # type: ignore[union-attr]
        .order_by(Recommendation.created_at.desc())  # type: ignore[attr-defined]
    ).all()
    return {"recommendations": [rec_service.view_full(r) for r in recs]}


@router.post("/{rec_id}/ack")
async def ack_recommendation(rec_id: str, db: Session = Depends(get_session)) -> dict:
    rec = rec_service.acknowledge(db, rec_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Recomendación no encontrada")

    # Transmite la actualización del dashboard en tiempo real tras desactivar la recomendación
    try:
        from app.services.dashboard import build_dashboard
        from app.services.websocket import manager
        db_data = build_dashboard(db)
        await manager.broadcast(db_data)
    except Exception:
        pass

    return rec_service.view_full(rec)
