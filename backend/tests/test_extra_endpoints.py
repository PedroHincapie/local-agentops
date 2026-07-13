"""Cobertura de endpoints sin tests: /api/ping, /api/ws/dashboard y large-files.

Estos existen en el código y en el contrato (§4.3.1, §4.9, §4.10) pero no estaban
cubiertos. Aquí se prueban su shape y sus casos borde.
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app
from app.services.sessions import get_large_files

client = TestClient(app)


def test_ping_liveness() -> None:
    r = client.get("/api/ping")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ws_dashboard_envia_payload_inicial_al_conectar(raw_statusline: dict) -> None:
    """Al conectar, el WS empuja de inmediato el estado del dashboard (§4.9)."""
    init_db()
    client.post("/api/snapshots", json=raw_statusline)

    with client.websocket_connect("/api/ws/dashboard") as ws:
        data = ws.receive_json()

    # Misma forma que GET /api/dashboard (§4.2).
    assert data["status"] == "green"
    assert "metrics" in data and "five_hour" in data["metrics"]
    assert data["metrics"]["five_hour"]["used_percentage"] == 45


def test_ws_dashboard_sin_datos_es_critical() -> None:
    """Sin snapshots no se inventa estado: el payload inicial es critical."""
    init_db()
    with client.websocket_connect("/api/ws/dashboard") as ws:
        data = ws.receive_json()
    assert data["status"] == "critical"


def test_large_files_sin_sesion_activa_404() -> None:
    init_db()
    r = client.get("/api/sessions/current/large-files")
    assert r.status_code == 404


def test_large_files_con_sesion_devuelve_lista(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)
    r = client.get("/api/sessions/current/large-files")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["files"], list)
    assert len(body["files"]) <= 5


def test_get_large_files_ordena_excluye_y_limita(tmp_path: Path) -> None:
    """Unidad: ordena por tamaño desc, excluye ruido de build y respeta el límite."""
    (tmp_path / "small.txt").write_bytes(b"x" * 10)
    (tmp_path / "big.txt").write_bytes(b"x" * 5000)
    (tmp_path / "mid.txt").write_bytes(b"x" * 1000)
    # Ruido que debe excluirse (directorio y sufijo).
    noise_dir = tmp_path / "node_modules"
    noise_dir.mkdir()
    (noise_dir / "huge.txt").write_bytes(b"x" * 100000)
    (tmp_path / "local.db").write_bytes(b"x" * 100000)

    files = get_large_files(str(tmp_path), limit=2)

    assert [f["path"] for f in files] == ["big.txt", "mid.txt"]  # ordenado y limitado
    assert files[0]["size_bytes"] == 5000
    assert files[0]["size_kb"] == round(5000 / 1024, 1)
    paths = {f["path"] for f in get_large_files(str(tmp_path), limit=99)}
    assert "node_modules/huge.txt" not in paths  # dir excluido
    assert "local.db" not in paths  # sufijo excluido


def test_get_large_files_ruta_invalida_devuelve_vacio() -> None:
    assert get_large_files(None) == []
    assert get_large_files("/ruta/que/no/existe/xyz") == []
