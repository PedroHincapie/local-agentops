"""Estado en memoria de la última reconciliación (insumo del futuro /api/health §4.8).

Proceso único y un solo usuario: basta un estado global en memoria; no requiere
persistencia. Se reinicia con el proceso.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class ReconcilerState:
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    healthy: bool | None = None  # None = aún no corrió
    last_error: str | None = None

    def record_success(self) -> None:
        now = datetime.now(UTC)
        self.last_run_at = now
        self.last_success_at = now
        self.healthy = True
        self.last_error = None

    def record_error(self, message: str) -> None:
        self.last_run_at = datetime.now(UTC)
        self.healthy = False
        self.last_error = message


state = ReconcilerState()
