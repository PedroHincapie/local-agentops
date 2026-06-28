"""Motor de recomendaciones (Hito 4). Básico, basado en las ventanas de límite.

Mapea el estado operativo (derivado del máx de las ventanas 5h/7d) a una recomendación
accionable. Para no inflar la tabla tick a tick, solo crea una recomendación nueva
cuando el **tipo cambia** respecto a la última de la jornada; al cambiar, la activa
previa se marca como superseded (``acknowledged_at``). Solo lo invoca la ingesta del
statusline, nunca el reconciliador ccusage (que no trae rate_limits).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.models import Recommendation

# status -> (recommendation_type, severity, message). Valores del contrato §4.7.
_BY_STATUS: dict[str, tuple[str, str, str]] = {
    "green": (
        "continue",
        "info",
        "Uso bajo. Continúa trabajando con normalidad.",
    ),
    "yellow": (
        "reduce_context",
        "warning",
        "Uso medio. Reduce el contexto o divide la tarea para no acelerar el consumo.",
    ),
    "red": (
        "reserve_for_critical",
        "warning",
        "Uso alto y poco margen. Reserva el agente para tareas críticas.",
    ),
    "critical": (
        "pause",
        "critical",
        "Límite alcanzado o sin datos confiables. Pausa hasta el próximo reset de ventana.",
    ),
}


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "?"
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def _build_reason(p5: float | None, p7: float | None) -> str:
    if p5 is None and p7 is None:
        return "Sin datos de rate_limits."
    return f"Ventana de 5h al {_fmt_pct(p5)}%, 7d al {_fmt_pct(p7)}%."


def active_recommendations(db: Session, workday_id: str) -> list[Recommendation]:
    """Recomendaciones activas (no vistas/superseded) de la jornada, más recientes primero."""
    return list(
        db.exec(
            select(Recommendation)
            .where(
                Recommendation.workday_id == workday_id,
                Recommendation.acknowledged_at.is_(None),  # type: ignore[union-attr]
            )
            .order_by(Recommendation.created_at.desc())  # type: ignore[attr-defined]
        ).all()
    )


def _latest(db: Session, workday_id: str) -> Recommendation | None:
    return db.exec(
        select(Recommendation)
        .where(Recommendation.workday_id == workday_id)
        .order_by(Recommendation.created_at.desc())  # type: ignore[attr-defined]
    ).first()


def refresh_for_snapshot(
    db: Session,
    workday_id: str,
    session_id: str | None,
    status: str,
    p5: float | None,
    p7: float | None,
) -> Recommendation | None:
    """Genera una recomendación si el estado cambió de tipo. Devuelve la nueva, o None."""
    rec_type, severity, message = _BY_STATUS.get(status, _BY_STATUS["critical"])

    latest = _latest(db, workday_id)
    if latest is not None and latest.recommendation_type == rec_type:
        return None  # mismo tipo: nada nuevo que recomendar

    # Cambio de estado: supersede las activas previas y crea la nueva.
    now = datetime.now(UTC)
    for stale in active_recommendations(db, workday_id):
        stale.acknowledged_at = now
        db.add(stale)

    rec = Recommendation(
        workday_id=workday_id,
        session_id=session_id,
        recommendation_type=rec_type,
        severity=severity,
        message=message,
        reason=_build_reason(p5, p7),
    )
    db.add(rec)
    return rec


def acknowledge(db: Session, rec_id: str) -> Recommendation | None:
    rec = db.get(Recommendation, rec_id)
    if rec is None:
        return None
    if rec.acknowledged_at is None:
        rec.acknowledged_at = datetime.now(UTC)
        db.add(rec)
        db.commit()
        db.refresh(rec)
    return rec


def _isoformat(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def view_brief(rec: Recommendation) -> dict[str, Any]:
    """Forma abreviada para el dashboard (§4.2)."""
    return {
        "id": rec.id,
        "recommendation_type": rec.recommendation_type,
        "severity": rec.severity,
        "message": rec.message,
        "reason": rec.reason,
    }


def view_full(rec: Recommendation) -> dict[str, Any]:
    """Forma completa para /api/recommendations (§4.7)."""
    return {
        "id": rec.id,
        "workday_id": rec.workday_id,
        "session_id": rec.session_id,
        "recommendation_type": rec.recommendation_type,
        "severity": rec.severity,
        "message": rec.message,
        "reason": rec.reason,
        "created_at": _isoformat(rec.created_at),
        "acknowledged_at": _isoformat(rec.acknowledged_at),
    }
