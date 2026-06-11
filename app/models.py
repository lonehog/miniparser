from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any


CompactPayload = dict[str, int | float | str | bool | None]


@dataclass(slots=True)
class ServiceSnapshot:
    name: str
    values: CompactPayload = field(default_factory=dict)
    ok: bool = False
    error: str | None = None
    updated_at: float | None = None

    def as_payload(self) -> CompactPayload:
        age = None if self.updated_at is None else max(0, int(time() - self.updated_at))
        payload: CompactPayload = dict(self.values)
        prefix = service_prefix(self.name)
        payload[f"{prefix}_ok"] = self.ok
        payload[f"{prefix}_age"] = age
        if self.error:
            payload[f"{prefix}_err"] = self.error[:96]
        return payload


def service_prefix(name: str) -> str:
    return {
        "glances": "g",
        "immich": "imm",
        "komodo": "kom",
        "proxmox": "pve",
        "uptime_kuma": "kuma",
        "whatsupdocker": "wud",
        "stirling": "st",
    }.get(name, name)


def number(value: Any, default: int | float = 0) -> int | float:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float):
        return value
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return int(parsed) if parsed.is_integer() else parsed


def percent(value: Any, default: int | float = 0) -> int | float:
    parsed = number(value, default)
    if isinstance(parsed, int | float) and 0 <= parsed <= 1:
        return round(parsed * 100, 1)
    return parsed

