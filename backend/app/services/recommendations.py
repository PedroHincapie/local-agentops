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
from app.services.providers import (
    latest_active_snapshot,
    latest_primary_snapshot,
    provider_margin,
    providers_with_data,
)
from app.services.status import derive_status

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

# Los tipos del flujo "estado" (uno activo a la vez). El flujo "switch_provider" es
# independiente: puede coexistir con una recomendación de estado.
_STATUS_TYPES: frozenset[str] = frozenset(t for t, _, _ in _BY_STATUS.values())
_SWITCH_TYPE = "switch_provider"
# Margen (puntos) que debe superar el mejor proveedor sobre el activo para sugerir
# el cambio: evita recomendar saltos marginales.
_SWITCH_MIN_DELTA = 20.0
_HEALTHY_ABS_MARGIN = 50.0  # margen "claramente sano" cuando el activo no tiene datos
_PROVIDER_LABELS = {"claude": "Claude", "codex": "Codex", "gemini": "Gemini"}


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


def _latest_of_types(
    db: Session, workday_id: str, types: frozenset[str]
) -> Recommendation | None:
    return db.exec(
        select(Recommendation)
        .where(
            Recommendation.workday_id == workday_id,
            Recommendation.recommendation_type.in_(list(types)),  # type: ignore[attr-defined]
        )
        .order_by(Recommendation.created_at.desc())  # type: ignore[attr-defined]
    ).first()


def _active_of_types(
    db: Session, workday_id: str, types: frozenset[str]
) -> list[Recommendation]:
    return [
        r for r in active_recommendations(db, workday_id) if r.recommendation_type in types
    ]


def refresh_for_snapshot(
    db: Session,
    workday_id: str,
    session_id: str | None,
    status: str,
    p5: float | None,
    p7: float | None,
) -> Recommendation | None:
    """Genera una recomendación de ESTADO si el tipo cambió. Devuelve la nueva, o None.

    Independiente del flujo ``switch_provider`` (ver ``refresh_switch_provider``).
    """
    rec_type, severity, message = _BY_STATUS.get(status, _BY_STATUS["critical"])

    latest = _latest_of_types(db, workday_id, _STATUS_TYPES)
    if latest is not None and latest.recommendation_type == rec_type:
        return None  # mismo tipo: nada nuevo que recomendar

    # Cambio de estado: supersede las activas de ESTADO previas y crea la nueva.
    now = datetime.now(UTC)
    for stale in _active_of_types(db, workday_id, _STATUS_TYPES):
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


def refresh_switch_provider(
    db: Session, workday_id: str, session_id: str | None = None
) -> Recommendation | None:
    """Sugiere cambiar de proveedor si el activo tiene poco margen y otro tiene más.

    Modo advisory: nombra el proveedor con más margen. Flujo independiente del de
    estado; deduplica por el par (activo -> objetivo) y se limpia cuando ya no aplica.
    """
    now = datetime.now(UTC)
    current = _latest_active_switch(db, workday_id)

    active_snap = latest_active_snapshot(db)
    active = active_snap.provider if active_snap else None
    active_status = (
        derive_status(
            active_snap.rate_limit_5h_percentage, active_snap.rate_limit_7d_percentage
        )
        if active_snap
        else "critical"
    )
    active_margin = provider_margin(active_snap)

    # Mejor proveedor por margen (entre los que tienen dato de ventana).
    best: str | None = None
    best_margin: float | None = None
    for provider in providers_with_data(db):
        margin = provider_margin(latest_primary_snapshot(db, provider))
        if margin is None:
            continue
        if best_margin is None or margin > best_margin:
            best, best_margin = provider, margin

    should = _should_switch(active, active_status, active_margin, best, best_margin)
    if not should:
        if current is not None:  # ya no aplica: limpiar el consejo
            current.acknowledged_at = now
            db.add(current)
        return None

    assert active is not None and best is not None  # _should_switch garantiza no-None
    la = _PROVIDER_LABELS.get(active, active)
    lb = _PROVIDER_LABELS.get(best, best)
    message = (
        f"Te queda más margen en {lb}. Considera cambiar de {la} a {lb} "
        f"para no depender del saldo de {la}."
    )
    if current is not None and current.message == message:
        return None  # mismo par activo->objetivo: nada nuevo

    if current is not None:
        current.acknowledged_at = now
        db.add(current)
    reason = (
        f"{la}: {active_status} ({_fmt_pct(active_margin)}% de margen); "
        f"{lb}: {_fmt_pct(best_margin)}% de margen."
    )
    rec = Recommendation(
        workday_id=workday_id,
        session_id=session_id,
        recommendation_type=_SWITCH_TYPE,
        severity="warning",
        message=message,
        reason=reason,
    )
    db.add(rec)
    return rec


def _should_switch(
    active: str | None,
    active_status: str,
    active_margin: float | None,
    best: str | None,
    best_margin: float | None,
) -> bool:
    if best is None or best_margin is None or active is None or best == active:
        return False
    if active_status == "green":
        return False  # el activo va bien: no hay razón para cambiar
    if active_margin is None:
        # Activo sin margen fiable (p.ej. critical por falta de datos): sugiere solo
        # si el mejor está claramente sano.
        return best_margin >= _HEALTHY_ABS_MARGIN
    return (best_margin - active_margin) >= _SWITCH_MIN_DELTA


def _latest_active_switch(db: Session, workday_id: str) -> Recommendation | None:
    return db.exec(
        select(Recommendation)
        .where(
            Recommendation.workday_id == workday_id,
            Recommendation.recommendation_type == _SWITCH_TYPE,
            Recommendation.acknowledged_at.is_(None),  # type: ignore[union-attr]
        )
        .order_by(Recommendation.created_at.desc())  # type: ignore[attr-defined]
    ).first()


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
