"""Hito 1: auto-detección de proyecto/sesión y métricas manuales."""
from __future__ import annotations

import copy
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import init_db
from app.main import app
from app.services.sessions import derive_git_branch, get_large_files

client = TestClient(app)


def test_sesion_se_autodetecta_y_aparece_en_dashboard(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)

    d = client.get("/api/dashboard").json()
    cs = d["current_session"]
    assert cs["id"] == raw_statusline["session_id"]
    assert cs["project_name"] == "proyecto-agentOps"
    assert cs["model_name"] == "Opus 4.8"
    # git_branch se deriva del repo del proyecto; en CI el path del fixture no existe
    # (o el checkout está en detached HEAD) -> puede ser None. La derivación se prueba
    # de forma hermética en test_derive_git_branch_*.
    assert "git_branch" in cs
    # Métricas manuales aún sin anotar.
    assert cs["task_type"] is None
    assert cs["objective"] is None
    assert cs["started_at"] is not None


def test_sessions_current_endpoint(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)

    r = client.get("/api/sessions/current")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == raw_statusline["session_id"]
    assert body["status"] == "active"
    assert body["snapshot_count"] == 1
    assert body["cost_session_usd"] == raw_statusline["cost"]["total_cost_usd"]


def test_patch_anota_objetivo_y_tipo_de_tarea(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)
    sid = raw_statusline["session_id"]

    r = client.patch(
        f"/api/sessions/{sid}",
        json={"objective": "Documentar el enrolamiento", "task_type": "documentación"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["objective"] == "Documentar el enrolamiento"
    assert body["task_type"] == "documentación"

    # La anotación se refleja en el dashboard.
    cs = client.get("/api/dashboard").json()["current_session"]
    assert cs["task_type"] == "documentación"
    assert cs["objective"] == "Documentar el enrolamiento"


def test_cambio_de_sesion_cierra_la_anterior(raw_statusline: dict) -> None:
    init_db()
    client.post("/api/snapshots", json=raw_statusline)

    other = copy.deepcopy(raw_statusline)
    other["session_id"] = "11111111-2222-3333-4444-555555555555"
    other["cost"]["total_cost_usd"] = 0.99
    client.post("/api/snapshots", json=other)

    # current = la nueva; la anterior queda cerrada (no es "current").
    current = client.get("/api/sessions/current").json()
    assert current["id"] == other["session_id"]


def test_patch_sesion_inexistente_da_404() -> None:
    init_db()
    r = client.patch("/api/sessions/no-existe", json={"objective": "x"})
    assert r.status_code == 404


def test_anotaciones_sobreviven_a_nuevos_snapshots(raw_statusline: dict) -> None:
    """Las métricas ``manual`` no deben pisarse cuando llega otro tick ``captured``.

    Regresión del flujo real: el usuario anota objetivo/tipo y luego el statusline
    sigue emitiendo snapshots de la misma sesión; la anotación tiene que persistir.
    """
    init_db()
    client.post("/api/snapshots", json=raw_statusline)
    sid = raw_statusline["session_id"]

    client.patch(
        f"/api/sessions/{sid}",
        json={"objective": "Documentar el enrolamiento", "task_type": "documentación"},
    )

    # Nuevo tick de la MISMA sesión (cambia el costo para no deduplicar).
    otro = copy.deepcopy(raw_statusline)
    otro["cost"]["total_cost_usd"] = raw_statusline["cost"]["total_cost_usd"] + 1.5
    client.post("/api/snapshots", json=otro)

    cs = client.get("/api/dashboard").json()["current_session"]
    assert cs["objective"] == "Documentar el enrolamiento"
    assert cs["task_type"] == "documentación"

    current = client.get("/api/sessions/current").json()
    assert current["objective"] == "Documentar el enrolamiento"
    assert current["task_type"] == "documentación"


def test_derive_git_branch_repo_temporal(tmp_path: Path) -> None:
    """Derivación hermética: rama de un repo git temporal (independiente del entorno)."""
    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    git("checkout", "-b", "rama-x")
    (tmp_path / "f.txt").write_text("x")
    git("add", ".")
    # Identidad inline: el runner de CI puede no tener git user configurado.
    git("-c", "user.name=t", "-c", "user.email=t@t.co", "commit", "-m", "init")
    assert derive_git_branch(str(tmp_path)) == "rama-x"


def test_derive_git_branch_sin_repo(tmp_path: Path) -> None:
    assert derive_git_branch(str(tmp_path / "no-es-repo")) is None
    assert derive_git_branch(None) is None


def test_large_files_excluye_ruido_de_build(tmp_path: Path) -> None:
    """``get_large_files`` debe listar archivos del trabajo, no artefactos de build."""
    # Artefacto pesado que NO debe aparecer.
    cache_dir = tmp_path / ".mypy_cache" / "3.11"
    cache_dir.mkdir(parents=True)
    (cache_dir / "cache.db").write_bytes(b"\0" * 2_000_000)
    # WAL de la base SQLite: excluido por sufijo aunque no esté en data/.
    (tmp_path / "local.db-wal").write_bytes(b"\0" * 1_500_000)
    # Archivo real del usuario (pequeño) que SÍ debe aparecer.
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_bytes(b"x" * 1024)

    files = get_large_files(str(tmp_path), limit=5)
    paths = {f["path"] for f in files}

    assert any(p.endswith("main.py") for p in paths)
    assert not any("mypy_cache" in p for p in paths)
    assert not any(p.endswith(".db-wal") for p in paths)
