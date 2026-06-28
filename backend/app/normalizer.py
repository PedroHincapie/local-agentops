"""Normalizador: JSON crudo del statusline de Claude Code -> snapshot normalizado.

El hook es "tonto" y reenvía el JSON tal cual; toda la lógica de mapeo vive aquí
(contrato §2). Tolera campos faltantes y ``current_usage: null``. Nunca inventa
valores: lo ausente queda en ``None``.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any


def _get(d: Any, *path: str) -> Any:
    """Acceso anidado tolerante: devuelve None si falta cualquier tramo."""
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _epoch_to_utc(value: Any) -> datetime | None:
    """Convierte un epoch Unix (s) a datetime UTC. None si no es numérico."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def content_hash(raw: dict[str, Any]) -> str:
    """Hash de contenido del tick para deduplicar ticks idénticos consecutivos.

    Combina (session_id + cost + rate_limits + context), ignorando timestamps de
    captura. Dos ticks con el mismo hash son el mismo estado.
    """
    material = {
        "session_id": _get(raw, "session_id"),
        "cost": raw.get("cost"),
        "rate_limits": raw.get("rate_limits"),
        "context_window": raw.get("context_window"),
    }
    blob = json.dumps(material, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """Mapea el JSON crudo a los campos de ``UsageSnapshot`` (contrato §2)."""
    return {
        "content_hash": content_hash(raw),
        # Identidad / workspace
        "session_external_id": _get(raw, "session_id"),
        "session_name": _get(raw, "session_name"),
        "transcript_path": _get(raw, "transcript_path"),
        "project_path": _get(raw, "workspace", "project_dir"),
        "current_dir": _get(raw, "workspace", "current_dir"),
        # Modelo / CLI
        "model_id": _get(raw, "model", "id"),
        "model_name": _get(raw, "model", "display_name"),
        "effort_level": _get(raw, "effort", "level"),
        "cli_version": _get(raw, "version"),
        # Costo / actividad
        "cost_session_usd": _get(raw, "cost", "total_cost_usd"),
        "session_duration_ms": _get(raw, "cost", "total_duration_ms"),
        "lines_added": _get(raw, "cost", "total_lines_added"),
        "lines_removed": _get(raw, "cost", "total_lines_removed"),
        # Contexto
        "context_window_size": _get(raw, "context_window", "context_window_size"),
        "context_used_percentage": _get(raw, "context_window", "used_percentage"),
        "total_input_tokens": _get(raw, "context_window", "total_input_tokens"),
        "total_output_tokens": _get(raw, "context_window", "total_output_tokens"),
        "cache_creation_input_tokens": _get(
            raw, "context_window", "current_usage", "cache_creation_input_tokens"
        ),
        "cache_read_input_tokens": _get(
            raw, "context_window", "current_usage", "cache_read_input_tokens"
        ),
        # Rate limits (official)
        "rate_limit_5h_percentage": _get(raw, "rate_limits", "five_hour", "used_percentage"),
        "rate_limit_5h_resets_at": _epoch_to_utc(
            _get(raw, "rate_limits", "five_hour", "resets_at")
        ),
        "rate_limit_7d_percentage": _get(raw, "rate_limits", "seven_day", "used_percentage"),
        "rate_limit_7d_resets_at": _epoch_to_utc(
            _get(raw, "rate_limits", "seven_day", "resets_at")
        ),
    }
