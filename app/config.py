from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, HttpUrl, ValidationError


class BaseServiceConfig(BaseModel):
    enabled: bool = True
    url: HttpUrl
    poll_interval_seconds: int | None = Field(default=None, ge=5)


class GlancesConfig(BaseServiceConfig):
    token_env: str | None = None
    disk_path: str = "/"


class ImmichConfig(BaseServiceConfig):
    api_key_env: str = "IMMICH_API_KEY"


class KomodoConfig(BaseServiceConfig):
    api_key_env: str = "KOMODO_API_KEY"
    api_secret_env: str = "KOMODO_API_SECRET"
    mode: Literal["summary", "containers", "stacks"] = "summary"


class ProxmoxConfig(BaseServiceConfig):
    token_id_env: str = "PROXMOX_TOKEN_ID"
    token_secret_env: str = "PROXMOX_TOKEN_SECRET"
    verify_tls: bool = True


class UptimeKumaConfig(BaseServiceConfig):
    api_key_env: str = "UPTIME_KUMA_API_KEY"


class WhatsUpDockerConfig(BaseServiceConfig):
    token_env: str | None = "WUD_TOKEN"


class StirlingConfig(BaseServiceConfig):
    health_path: str = "/"


class ServicesConfig(BaseModel):
    glances: GlancesConfig | None = None
    immich: ImmichConfig | None = None
    komodo: KomodoConfig | None = None
    proxmox: ProxmoxConfig | None = None
    uptime_kuma: UptimeKumaConfig | None = None
    whatsupdocker: WhatsUpDockerConfig | None = None
    stirling: StirlingConfig | None = None


class AppConfig(BaseModel):
    poll_interval_seconds: int = Field(default=30, ge=5)
    timeout_seconds: float = Field(default=5, gt=0)
    esp_token_env: str = "ESP_BEARER_TOKEN"
    services: ServicesConfig = Field(default_factory=ServicesConfig)

    @property
    def esp_token(self) -> str | None:
        return read_secret(self.esp_token_env)


def read_secret(name: str | None) -> str | None:
    if not name:
        return None
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path or os.getenv("CONFIG_PATH", "config.yml"))
    if not config_path.exists():
        return AppConfig()

    with config_path.open("r", encoding="utf-8") as handle:
        raw: dict[str, Any] = yaml.safe_load(handle) or {}

    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise RuntimeError(f"Invalid config file {config_path}: {exc}") from exc
