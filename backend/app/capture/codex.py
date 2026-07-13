"""``CodexSource``: lee el uso/límites de OpenAI Codex CLI (fuente pull, sin sesión).

Codex escribe transcripciones por sesión en ``~/.codex/sessions/YYYY/MM/DD/
rollout-*.jsonl``. Dentro, algunos eventos llevan un objeto ``rate_limits`` y el
uso acumulado de tokens. Tomamos el **último** de esos valores del rollout más
reciente. Solo se leen los campos de uso/límites, nunca la conversación.

Formato real de ``rate_limits`` (validado contra un rollout real):
``{"primary": {"used_percent": 32.0, "window_minutes": 10080, "resets_at": <epoch>},
   "secondary": null, "plan_type": "plus"}``. OJO: ``primary``/``secondary`` NO son
posicionalmente 5h/7d — se clasifican por ``window_minutes`` (≈300 → 5h, ≈10080 → 7d).
``rate_limits`` puede venir ``null`` (bug conocido openai/codex#14880): se degrada.
"""
from __future__ import annotations

import glob
import json
import os
from datetime import UTC, datetime
from typing import Any

from app.capture.base import NormalizedFields
from app.config import settings

# Umbral para clasificar una ventana por su duración: <= 10h se considera la de 5h.
_FIVE_HOUR_MAX_MINUTES = 600


def _epoch_to_utc(epoch: Any) -> datetime | None:
    if epoch is None:
        return None
    try:
        return datetime.fromtimestamp(float(epoch), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _find_key(obj: Any, key: str) -> Any:
    """Primer valor de ``key`` hallado recursivamente, o None."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = _find_key(v, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_key(v, key)
            if r is not None:
                return r
    return None


class CodexSource:
    name = "codex"
    provider = "codex"
    source_name = "codex_rollout"

    def __init__(self, sessions_dir: str | None = None) -> None:
        raw = sessions_dir or settings.codex_sessions_dir
        self._sessions_dir = os.path.expanduser(raw)

    def fetch(self) -> NormalizedFields | None:
        path = self._latest_rollout()
        if path is None:
            return None
        rate_limits, usage, context_window = self._scan(path)
        if rate_limits is None and usage is None:
            return None
        fields: NormalizedFields = {
            "context_window_size": context_window,
        }
        fields.update(self._map_tokens(usage))
        fields.update(self._map_rate_limits(rate_limits))
        return fields

    def _latest_rollout(self) -> str | None:
        pattern = os.path.join(self._sessions_dir, "**", "rollout-*.jsonl")
        files = glob.glob(pattern, recursive=True)
        if not files:
            return None
        return max(files, key=os.path.getmtime)

    @staticmethod
    def _scan(path: str) -> tuple[dict | None, dict | None, int | None]:
        """Último rate_limits + uso de tokens + tamaño de contexto del rollout.

        Solo se parsean las líneas que contienen los marcadores de uso/límites
        (evita cargar los eventos de conversación).
        """
        rate_limits: dict | None = None
        usage: dict | None = None
        context_window: int | None = None
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if '"rate_limits"' not in line and '"total_token_usage"' not in line:
                        continue
                    try:
                        o = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    rl = _find_key(o, "rate_limits")
                    if isinstance(rl, dict):
                        rate_limits = rl
                    u = _find_key(o, "total_token_usage")
                    if isinstance(u, dict):
                        usage = u
                    cw = _find_key(o, "model_context_window")
                    if isinstance(cw, int):
                        context_window = cw
        except OSError:
            return None, None, None
        return rate_limits, usage, context_window

    @staticmethod
    def _map_tokens(usage: dict | None) -> NormalizedFields:
        if not usage:
            return {}
        return {
            "total_input_tokens": usage.get("input_tokens"),
            "total_output_tokens": usage.get("output_tokens"),
            "cache_read_input_tokens": usage.get("cached_input_tokens"),
        }

    @staticmethod
    def _map_rate_limits(rate_limits: dict | None) -> NormalizedFields:
        """Clasifica primary/secondary por ``window_minutes`` en 5h/7d. Degrada a None."""
        out: NormalizedFields = {
            "rate_limit_5h_percentage": None,
            "rate_limit_5h_resets_at": None,
            "rate_limit_7d_percentage": None,
            "rate_limit_7d_resets_at": None,
        }
        if not rate_limits:
            return out
        for slot in (rate_limits.get("primary"), rate_limits.get("secondary")):
            if not isinstance(slot, dict):
                continue
            pct = slot.get("used_percent")
            wm = slot.get("window_minutes")
            resets = _epoch_to_utc(slot.get("resets_at"))
            if wm is None:
                continue
            if wm <= _FIVE_HOUR_MAX_MINUTES:
                out["rate_limit_5h_percentage"] = pct
                out["rate_limit_5h_resets_at"] = resets
            else:
                out["rate_limit_7d_percentage"] = pct
                out["rate_limit_7d_resets_at"] = resets
        return out
