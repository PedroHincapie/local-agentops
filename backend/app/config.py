"""Configuración del backend (pydantic-settings).

Lee de variables de entorno con prefijo ``AGENTOPS_`` y/o un archivo ``.env``.
Los umbrales de estado son configurables; el resto de invariantes vive en código.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AGENTOPS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8787
    db_url: str = "sqlite:///./data/local-agentops.db"

    # Umbrales de estado: peak = max(5h%, 7d%).
    #   peak < yellow            -> green
    #   yellow <= peak < red     -> yellow
    #   red <= peak < critical   -> red
    #   peak >= critical         -> critical
    threshold_yellow: float = 50
    threshold_red: float = 80
    threshold_critical: float = 95

    reconcile_interval_seconds: int = 300
    # Cierre auto de sesión: si la sesión activa no recibe snapshots por más de este
    # tiempo, se marca ``closed`` (barrido proactivo en el reconciliador + chequeo perezoso).
    session_idle_minutes: int = 120

    # --- Fuentes multi-provider (pull). Deshabilitadas por defecto: se activan cuando
    # el usuario usa esos CLIs. Claude no necesita flag (statusline hook + ccusage). ---
    codex_enabled: bool = False
    codex_sessions_dir: str = "~/.codex/sessions"
    gemini_enabled: bool = False
    gemini_telemetry_log: str = "~/.gemini/telemetry.log"
    # Cuota del tier de Gemini (RPD/TPM): margen ESTIMADO. 0 = desconocida (no se estima).
    gemini_rpd: int = 0
    gemini_tpm: int = 0
    scheduler_enabled: bool = True  # tests/CI pueden apagarlo (AGENTOPS_SCHEDULER_ENABLED=false)
    frontend_dist: str = "../frontend/public"  # deliverable estático servido en /

    # CORS SOLO para desarrollo: cuando el dashboard se abre desde otro origen
    # (archivo local o Vite dev). En operación normal el backend sirve el SPA en
    # el mismo origen y CORS queda apagado (ver CLAUDE.md).
    dev_cors: bool = False


settings = Settings()
