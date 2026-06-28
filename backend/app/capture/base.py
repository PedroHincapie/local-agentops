"""Interfaz interna ``CaptureSource``.

Única abstracción que se conserva del diseño multi-provider abandonado: aísla la
volatilidad de las fuentes (statusline, ccusage) sin reintroducir una capa de
providers. Agregar o sustituir una fuente no debe tocar el dashboard (CLAUDE.md).

``fetch()`` devuelve un dict de campos normalizados de ``UsageSnapshot`` (los que
la fuente puede aportar), o ``None`` si no hay datos. La clasificación de origen
(``source_type`` / ``source_name``) la fija quien persiste, no la fuente.
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
    name: str

    def fetch(self) -> NormalizedFields | None: ...
