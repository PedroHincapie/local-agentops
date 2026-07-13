"""Interfaz interna ``CaptureSource``.

Única abstracción que se conserva del diseño multi-provider abandonado: aísla la
volatilidad de las fuentes (statusline, ccusage) sin reintroducir una capa de
providers. Agregar o sustituir una fuente no debe tocar el dashboard (CLAUDE.md).

``fetch()`` devuelve un dict de campos normalizados de ``UsageSnapshot`` (los que
la fuente puede aportar), o ``None`` si no hay datos.

Cada fuente declara su identidad multi-provider: ``provider`` (la cuenta: claude |
codex | gemini) y ``source_name`` (el mecanismo: statusline | ccusage | codex_rollout
| gemini_otel). Quien persiste usa esas dos etiquetas; la fuente no toca el dashboard.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

NormalizedFields = dict[str, Any]


class CaptureError(Exception):
    """Fallo recuperable de una fuente (comando ausente, JSON inválido, etc.).

    Se captura arriba y se registra; nunca tumba el proceso ni el dashboard.
    """


@runtime_checkable
class CaptureSource(Protocol):
    name: str  # id humano para logs
    provider: str  # claude | codex | gemini
    source_name: str  # statusline | ccusage | codex_rollout | gemini_otel

    def fetch(self) -> NormalizedFields | None: ...
