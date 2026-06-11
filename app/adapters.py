from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from time import perf_counter
from typing import Any
from urllib.parse import urljoin

import httpx

from app.config import (
    GlancesConfig,
    ImmichConfig,
    KomodoConfig,
    ProxmoxConfig,
    StirlingConfig,
    UptimeKumaConfig,
    WhatsUpDockerConfig,
    read_secret,
)
from app.models import CompactPayload, number, percent


class Adapter(ABC):
    name: str
    verify_tls: bool = True

    @abstractmethod
    async def fetch(self, client: httpx.AsyncClient) -> CompactPayload:
        raise NotImplementedError


def clean_base(url: Any) -> str:
    return str(url).rstrip("/") + "/"


async def get_json(
    client: httpx.AsyncClient,
    base_url: Any,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
) -> Any:
    response = await client.get(urljoin(clean_base(base_url), path.lstrip("/")), headers=headers, params=params)
    response.raise_for_status()
    return response.json()


def first_present(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return default


class GlancesAdapter(Adapter):
    name = "glances"

    def __init__(self, config: GlancesConfig):
        self.config = config

    async def fetch(self, client: httpx.AsyncClient) -> CompactPayload:
        headers = {}
        if token := read_secret(self.config.token_env):
            headers["Authorization"] = f"Bearer {token}"

        cpu_task = get_json(client, self.config.url, "/api/4/cpu", headers=headers)
        mem_task = get_json(client, self.config.url, "/api/4/mem", headers=headers)
        swap_task = get_json(client, self.config.url, "/api/4/memswap", headers=headers)
        uptime_task = get_json(client, self.config.url, "/api/4/uptime", headers=headers)
        fs_task = get_json(client, self.config.url, "/api/4/fs", headers=headers)
        sensors_task = get_json(client, self.config.url, "/api/4/sensors", headers=headers)
        cpu, mem, swap, uptime, fs, sensors = await asyncio.gather(
            cpu_task,
            mem_task,
            swap_task,
            uptime_task,
            fs_task,
            sensors_task,
            return_exceptions=True,
        )

        payload: CompactPayload = {
            "g_cpu": percent(_safe_get(cpu, "total")),
            "g_mem": percent(_safe_get(mem, "percent")),
            "g_swap": percent(_safe_get(swap, "percent")),
            "g_uptime": number(_safe_get(uptime, "seconds")),
        }

        disk_percent = _disk_percent(fs, self.config.disk_path)
        if disk_percent is not None:
            payload["g_disk_pct"] = percent(disk_percent)

        temp = _sensor_temp(sensors)
        if temp is not None:
            payload["g_temp"] = number(temp)

        return payload


class ImmichAdapter(Adapter):
    name = "immich"

    def __init__(self, config: ImmichConfig):
        self.config = config

    async def fetch(self, client: httpx.AsyncClient) -> CompactPayload:
        api_key = read_secret(self.config.api_key_env)
        headers = {"x-api-key": api_key} if api_key else {}
        stats = await get_json(client, self.config.url, "/api/server/statistics", headers=headers)
        return {
            "imm_users": number(first_present(stats, "users", "userCount")),
            "imm_photos": number(first_present(stats, "photos", "photosCount")),
            "imm_videos": number(first_present(stats, "videos", "videosCount")),
            "imm_storage": number(first_present(stats, "usage", "diskUsageRaw", "storage")),
        }


class KomodoAdapter(Adapter):
    name = "komodo"

    def __init__(self, config: KomodoConfig):
        self.config = config

    async def fetch(self, client: httpx.AsyncClient) -> CompactPayload:
        headers = {}
        key = read_secret(self.config.api_key_env)
        secret = read_secret(self.config.api_secret_env)
        if key:
            headers["X-API-Key"] = key
        if secret:
            headers["X-API-Secret"] = secret

        endpoint = {
            "summary": "/api/stats/summary",
            "containers": "/api/stats/containers",
            "stacks": "/api/stats/stacks",
        }[self.config.mode]
        data = await get_json(client, self.config.url, endpoint, headers=headers)

        if self.config.mode == "summary":
            return {
                "kom_servers": number(first_present(data, "servers", "serverCount")),
                "kom_stacks": number(first_present(data, "stacks", "stackCount")),
                "kom_containers": number(first_present(data, "containers", "containerCount")),
            }

        if self.config.mode == "containers":
            return _status_payload("kom", data, ["running", "stopped", "unhealthy", "unknown"])

        return _status_payload("kom", data, ["running", "down", "unhealthy", "unknown"])


class ProxmoxAdapter(Adapter):
    name = "proxmox"

    def __init__(self, config: ProxmoxConfig):
        self.config = config
        self.verify_tls = config.verify_tls

    async def fetch(self, client: httpx.AsyncClient) -> CompactPayload:
        token_id = read_secret(self.config.token_id_env)
        token_secret = read_secret(self.config.token_secret_env)
        headers = {}
        if token_id and token_secret:
            headers["Authorization"] = f"PVEAPIToken={token_id}={token_secret}"

        data = await get_json(client, self.config.url, "/api2/json/cluster/resources", headers=headers)
        resources = data.get("data", data if isinstance(data, list) else [])
        vms = [item for item in resources if item.get("type") == "qemu"]
        lxcs = [item for item in resources if item.get("type") == "lxc"]
        nodes = [item for item in resources if item.get("type") == "node"]
        return {
            "pve_vms": len(vms),
            "pve_lxc": len(lxcs),
            "pve_cpu": round(_average_percent(nodes, "cpu"), 1),
            "pve_mem": round(_sum_ratio_percent(nodes, "mem", "maxmem"), 1),
        }


class UptimeKumaAdapter(Adapter):
    name = "uptime_kuma"

    def __init__(self, config: UptimeKumaConfig):
        self.config = config

    async def fetch(self, client: httpx.AsyncClient) -> CompactPayload:
        headers = {}
        if token := read_secret(self.config.api_key_env):
            headers["Authorization"] = f"Bearer {token}"
        data = await get_json(client, self.config.url, "/api/status-page/heartbeat", headers=headers)
        monitors = _items(data, "monitors")
        if isinstance(monitors, dict):
            monitors = list(monitors.values())
        up = sum(1 for item in monitors if _monitor_up(item))
        total = len(monitors)
        down = max(total - up, 0)
        uptime = round((up / total) * 100, 2) if total else 0
        return {
            "kuma_up": up,
            "kuma_down": down,
            "kuma_uptime": uptime,
            "kuma_incident": down > 0,
        }


class WhatsUpDockerAdapter(Adapter):
    name = "whatsupdocker"

    def __init__(self, config: WhatsUpDockerConfig):
        self.config = config

    async def fetch(self, client: httpx.AsyncClient) -> CompactPayload:
        headers = {}
        if token := read_secret(self.config.token_env):
            headers["Authorization"] = f"Bearer {token}"
        data = await get_json(client, self.config.url, "/api/containers", headers=headers)
        containers = _items(data, "containers")
        monitoring = len(containers)
        updates = sum(1 for item in containers if _has_update(item))
        return {"wud_monitoring": monitoring, "wud_updates": updates}


class StirlingAdapter(Adapter):
    name = "stirling"

    def __init__(self, config: StirlingConfig):
        self.config = config

    async def fetch(self, client: httpx.AsyncClient) -> CompactPayload:
        start = perf_counter()
        response = await client.get(urljoin(clean_base(self.config.url), self.config.health_path.lstrip("/")))
        response.raise_for_status()
        return {"st_ok": True, "st_ms": round((perf_counter() - start) * 1000)}


def _safe_get(value: Any, key: str) -> Any:
    if isinstance(value, Exception):
        return None
    if isinstance(value, dict):
        return value.get(key)
    return None


def _items(data: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    value = data.get(key, data.get("data", []))
    if isinstance(value, dict):
        return [item for item in value.values() if isinstance(item, dict)]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _disk_percent(fs: Any, path: str) -> Any:
    if isinstance(fs, Exception):
        return None
    items = fs if isinstance(fs, list) else fs.get("data", []) if isinstance(fs, dict) else []
    for item in items:
        if item.get("mnt_point") == path or item.get("mountpoint") == path:
            return first_present(item, "percent", "used_percent")
    if items:
        return first_present(items[0], "percent", "used_percent")
    return None


def _sensor_temp(sensors: Any) -> Any:
    if isinstance(sensors, Exception):
        return None
    items = sensors if isinstance(sensors, list) else sensors.get("temperatures", []) if isinstance(sensors, dict) else []
    temps = [number(first_present(item, "value", "temperature"), None) for item in items]
    temps = [temp for temp in temps if isinstance(temp, int | float)]
    return max(temps) if temps else None


def _status_payload(prefix: str, data: dict[str, Any], statuses: list[str]) -> CompactPayload:
    total = number(first_present(data, "total", "count"))
    payload: CompactPayload = {f"{prefix}_total": total}
    for status in statuses:
        payload[f"{prefix}_{status}"] = number(first_present(data, status, status.capitalize()))
    return payload


def _average_percent(items: list[dict[str, Any]], key: str) -> float:
    values = [percent(item.get(key)) for item in items if item.get(key) is not None]
    return sum(values) / len(values) if values else 0


def _sum_ratio_percent(items: list[dict[str, Any]], used_key: str, max_key: str) -> float:
    used = sum(number(item.get(used_key)) for item in items)
    maximum = sum(number(item.get(max_key)) for item in items)
    return (used / maximum) * 100 if maximum else 0


def _monitor_up(item: dict[str, Any]) -> bool:
    status = first_present(item, "status", "active", "up")
    return status in (1, True, "1", "up", "UP", "online", "Online")


def _has_update(item: dict[str, Any]) -> bool:
    value = first_present(item, "updateAvailable", "update_available", "hasUpdate", "result")
    if isinstance(value, dict):
        value = first_present(value, "updateAvailable", "hasUpdate")
    return value in (1, True, "true", "available", "update-available")
