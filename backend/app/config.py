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
    scheduler_enabled: bool = True  # tests/CI pueden apagarlo (AGENTOPS_SCHEDULER_ENABLED=false)
    frontend_dist: str = "../frontend/dist"


settings = Settings()
