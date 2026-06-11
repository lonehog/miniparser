from __future__ import annotations

import asyncio
from time import time

import httpx

from app.adapters import Adapter
from app.models import CompactPayload, ServiceSnapshot


class SnapshotCache:
    def __init__(self) -> None:
        self._snapshots: dict[str, ServiceSnapshot] = {}
        self._lock = asyncio.Lock()

    async def update_success(self, name: str, values: CompactPayload) -> None:
        async with self._lock:
            self._snapshots[name] = ServiceSnapshot(name=name, values=values, ok=True, updated_at=time())

    async def update_failure(self, name: str, error: str) -> None:
        async with self._lock:
            current = self._snapshots.get(name)
            if current is None:
                self._snapshots[name] = ServiceSnapshot(name=name, ok=False, error=error, updated_at=None)
            else:
                current.ok = False
                current.error = error

    async def payload(self) -> CompactPayload:
        async with self._lock:
            output: CompactPayload = {"ts": int(time())}
            for name in sorted(self._snapshots):
                output.update(self._snapshots[name].as_payload())
            return output

    async def has_any_success(self) -> bool:
        async with self._lock:
            return any(snapshot.updated_at is not None for snapshot in self._snapshots.values())


class Poller:
    def __init__(
        self,
        adapters: list[Adapter],
        cache: SnapshotCache,
        *,
        interval_seconds: int,
        timeout_seconds: float,
    ) -> None:
        self.adapters = adapters
        self.cache = cache
        self.interval_seconds = interval_seconds
        self.timeout_seconds = timeout_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="miniparser-poller")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def refresh_once(self) -> None:
        await asyncio.gather(*(self._refresh_adapter(adapter) for adapter in self.adapters))

    async def _run(self) -> None:
        while not self._stop.is_set():
            await self.refresh_once()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                continue

    async def _refresh_adapter(self, adapter: Adapter) -> None:
        try:
            timeout = httpx.Timeout(self.timeout_seconds)
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                verify=adapter.verify_tls,
            ) as client:
                values = await adapter.fetch(client)
        except Exception as exc:
            await self.cache.update_failure(adapter.name, f"{type(exc).__name__}: {exc}")
            return
        await self.cache.update_success(adapter.name, values)
