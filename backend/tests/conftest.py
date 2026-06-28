"""Configura una DB SQLite temporal ANTES de importar la app.

El engine se crea al importar ``app.db``; por eso fijamos ``AGENTOPS_DB_URL`` aquí,
en el import de conftest (que pytest carga antes que los tests).
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

_TMPDIR = tempfile.mkdtemp(prefix="agentops-test-")
os.environ["AGENTOPS_DB_URL"] = f"sqlite:///{_TMPDIR}/test.db"

import pytest  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def raw_statusline() -> dict:
    return json.loads((FIXTURES / "statusline_real.json").read_text())
