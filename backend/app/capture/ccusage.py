"""``CcusageSource``: reconcilia costo/tokens leyendo ``ccusage`` (red de seguridad).

ccusage agrega los logs locales de Claude Code (``~/.claude/projects/**/*.jsonl``),
así que recupera uso ocurrido mientras el backend estuvo caído. **No** aporta
``rate_limits`` oficiales (esos solo vienen del statusline): los deja en ``None``.

Esquema real de ``ccusage blocks --active --json`` (validado contra ccusage):
``{"blocks": [{"isActive": true, "costUSD": ..., "models": ["claude-opus-4-8"],
   "tokenCounts": {"inputTokens", "outputTokens",
                   "cacheCreationInputTokens", "cacheReadInputTokens"}}]}``
"""
from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from typing import Any

from app.capture.base import CaptureError, NormalizedFields

# Comando base: sin instalación global (npx/bunx), per CLAUDE.md.
_DEFAULT_BASE_CMD = ["npx", "-y", "ccusage@latest"]

CommandRunner = Callable[[list[str]], str]


def _default_runner(args: list[str]) -> str:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=90)
    except FileNotFoundError as e:  # npx/ccusage no disponible
        raise CaptureError(f"comando no encontrado: {args[0]}") from e
    except subprocess.SubprocessError as e:  # timeout u otros
        raise CaptureError(f"fallo ejecutando ccusage: {e}") from e
    if result.returncode != 0:
        raise CaptureError(
            f"ccusage salió {result.returncode}: {result.stderr.strip()[:200]}"
        )
    return result.stdout


class CcusageSource:
    name = "ccusage"
    provider = "claude"
    source_name = "ccusage"

    def __init__(
        self,
        runner: CommandRunner | None = None,
        base_cmd: list[str] | None = None,
    ) -> None:
        self._runner = runner or _default_runner
        self._base_cmd = base_cmd or _DEFAULT_BASE_CMD

    def fetch(self) -> NormalizedFields | None:
        """Bloque de 5h activo mapeado a campos de snapshot, o None si no hay."""
        raw = self._load_json([*self._base_cmd, "blocks", "--active", "--json"])
        block = self._active_block(raw)
        if block is None:
            return None
        return self._map_block(block)

    def _load_json(self, args: list[str]) -> Any:
        out = self._runner(args)
        try:
            return json.loads(out)
        except json.JSONDecodeError as e:
            raise CaptureError(f"ccusage: salida no es JSON válido: {e}") from e

    @staticmethod
    def _active_block(raw: Any) -> dict[str, Any] | None:
        blocks = raw.get("blocks") if isinstance(raw, dict) else None
        if not blocks:
            return None
        for b in blocks:
            if isinstance(b, dict) and b.get("isActive"):
                return b
        first = blocks[0]
        return first if isinstance(first, dict) else None

    @staticmethod
    def _map_block(block: dict[str, Any]) -> NormalizedFields:
        tokens = block.get("tokenCounts") or {}
        models = block.get("models") or []
        model = models[0] if models else None
        return {
            "model_id": model,
            "model_name": model,  # ccusage da el id del modelo, no el display name
            "cost_session_usd": block.get("costUSD"),
            "total_input_tokens": tokens.get("inputTokens"),
            "total_output_tokens": tokens.get("outputTokens"),
            "cache_creation_input_tokens": tokens.get("cacheCreationInputTokens"),
            "cache_read_input_tokens": tokens.get("cacheReadInputTokens"),
            # rate_limits: ausentes en ccusage -> None (nunca se inventan).
            "rate_limit_5h_percentage": None,
            "rate_limit_7d_percentage": None,
        }
