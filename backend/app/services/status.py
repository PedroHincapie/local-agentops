"""Derivación del estado operativo a partir de las ventanas de rate limit.

``status`` = función del MAYOR porcentaje entre las dos ventanas oficiales (5h, 7d).
Sin datos de rate_limits -> ``critical`` (no se inventa). Contrato §3.
"""
from __future__ import annotations

from app.config import settings


def derive_status(
    five_hour_pct: float | None, seven_day_pct: float | None
) -> str:
    values = [v for v in (five_hour_pct, seven_day_pct) if v is not None]
    if not values:
        return "critical"  # sin señal confiable: no se asume "green"
    peak = max(values)
    if peak < settings.threshold_yellow:
        return "green"
    if peak < settings.threshold_red:
        return "yellow"
    if peak < settings.threshold_critical:
        return "red"
    return "critical"
