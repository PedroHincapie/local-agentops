"""Dimensión multi-provider: fuentes primarias por proveedor y helpers de lectura.

Centraliza el concepto de "fuente primaria/viva" de cada proveedor (la que trae las
ventanas/estado autoritativos), para que la capa de lectura deje de asumir un único
proveedor (``source_name == "statusline"``). Los ticks de reconciliación (p. ej.
``ccusage``) NO son primarios.
"""
from __future__ import annotations

from sqlmodel import Session, select

from app.models import UsageSnapshot

# Orden de presentación de proveedores en el dashboard.
ALL_PROVIDERS: tuple[str, ...] = ("claude", "codex", "gemini")

# Fuente primaria de cada proveedor: el feed en vivo que trae ventanas/estado.
PRIMARY_SOURCE_BY_PROVIDER: dict[str, str] = {
    "claude": "statusline",
    "codex": "codex_rollout",
    "gemini": "gemini_otel",
}
PRIMARY_SOURCE_NAMES: list[str] = list(PRIMARY_SOURCE_BY_PROVIDER.values())


def latest_primary_snapshot(db: Session, provider: str) -> UsageSnapshot | None:
    """Último snapshot primario de un proveedor (su feed en vivo)."""
    src = PRIMARY_SOURCE_BY_PROVIDER.get(provider)
    if src is None:
        return None
    return db.exec(
        select(UsageSnapshot)
        .where(UsageSnapshot.provider == provider, UsageSnapshot.source_name == src)
        .order_by(UsageSnapshot.captured_at.desc())  # type: ignore[attr-defined]
    ).first()


def latest_active_snapshot(db: Session) -> UsageSnapshot | None:
    """Último snapshot primario entre TODOS los proveedores: define el proveedor activo."""
    return db.exec(
        select(UsageSnapshot)
        .where(UsageSnapshot.source_name.in_(PRIMARY_SOURCE_NAMES))  # type: ignore[attr-defined]
        .order_by(UsageSnapshot.captured_at.desc())  # type: ignore[attr-defined]
    ).first()


def providers_with_data(db: Session) -> list[str]:
    """Proveedores que tienen al menos un snapshot primario, en orden de presentación."""
    return [p for p in ALL_PROVIDERS if latest_primary_snapshot(db, p) is not None]


def provider_margin(snap: UsageSnapshot | None) -> float | None:
    """Margen 0–100 del proveedor = 100 − max(ventanas). None si no hay datos de ventana.

    Uso INTERNO para rankear (``recommended_provider``); la UI muestra métricas nativas.
    """
    if snap is None:
        return None
    vals = [
        v
        for v in (snap.rate_limit_5h_percentage, snap.rate_limit_7d_percentage)
        if v is not None
    ]
    if not vals:
        return None
    return 100.0 - max(vals)
