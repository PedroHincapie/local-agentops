"""Reconciliador (red de seguridad · pull). Lo invoca el scheduler cada N minutos.

Per CLAUDE.md: **no** es captura primaria. Solo actúa si hay jornada activa del día
(no abre jornada), recupera costo/tokens vía ccusage y persiste un snapshot tagueado
``source_name="ccusage"``. Tolera fallos de la fuente: los registra en el estado del
reconciliador sin romper el proceso ni el dashboard.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.capture.base import CaptureError, CaptureSource
from app.capture.ccusage import CcusageSource
from app.db import engine
from app.models import UsageSnapshot, Workday
from app.services.reconciler_state import state
from app.services.sessions import close_idle_sessions

# Campos que definen el contenido de un tick ccusage (para deduplicar).
_HASH_KEYS = (
    "cost_session_usd",
    "total_input_tokens",
    "total_output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def _content_hash(fields: dict[str, Any]) -> str:
    material = {k: fields.get(k) for k in _HASH_KEYS}
    blob = json.dumps(material, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _today_local() -> str:
    return datetime.now().date().isoformat()


def _active_workday(db: Session) -> Workday | None:
    """Jornada activa de HOY. No la crea: el reconciliador no genera actividad."""
    return db.exec(
        select(Workday).where(
            Workday.date == _today_local(), Workday.status == "active"
        )
    ).first()


def reconcile_once(source: CaptureSource | None = None) -> dict[str, Any]:
    """Una pasada de reconciliación. Devuelve un resumen (útil para logs/tests)."""
    src = source or CcusageSource()
    with Session(engine) as db:
        # Barrido proactivo: cierra sesiones inactivas aunque nadie consulte
        # /api/sessions/current (independiente de que haya jornada activa).
        idle_closed = close_idle_sessions(db)

        workday = _active_workday(db)
        if workday is None:
            # Sin actividad del día: nada que reconciliar.
            return {
                "reconciled": False,
                "reason": "sin jornada activa",
                "idle_sessions_closed": idle_closed,
            }

        try:
            fields = src.fetch()
        except CaptureError as e:
            state.record_error(f"{src.name}: {e}")
            return {"reconciled": False, "reason": "error de captura", "error": str(e)}

        if fields is None:
            state.record_success()
            return {"reconciled": False, "reason": "ccusage sin bloque activo"}

        content_hash = _content_hash(fields)
        last = db.exec(
            select(UsageSnapshot)
            .where(UsageSnapshot.source_name == "ccusage")
            .order_by(UsageSnapshot.captured_at.desc())  # type: ignore[attr-defined]
        ).first()
        if last is not None and last.content_hash == content_hash:
            state.record_success()
            return {"reconciled": False, "reason": "sin cambios"}

        snapshot = UsageSnapshot(
            workday_id=workday.id,
            captured_at=datetime.now(UTC),
            source_type="captured",
            source_name="ccusage",
            content_hash=content_hash,
            **fields,
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)
        state.record_success()
        return {"reconciled": True, "snapshot_id": snapshot.id, "workday_id": workday.id}
