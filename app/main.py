from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app import __version__
from app.adapters import (
    GlancesAdapter,
    ImmichAdapter,
    KomodoAdapter,
    ProxmoxAdapter,
    StirlingAdapter,
    UptimeKumaAdapter,
    WhatsUpDockerAdapter,
)
from app.cache import Poller, SnapshotCache
from app.config import AppConfig, load_config


def build_adapters(config: AppConfig):
    services = config.services
    adapters = []
    if services.glances and services.glances.enabled:
        adapters.append(GlancesAdapter(services.glances))
    if services.immich and services.immich.enabled:
        adapters.append(ImmichAdapter(services.immich))
    if services.komodo and services.komodo.enabled:
        adapters.append(KomodoAdapter(services.komodo))
    if services.proxmox and services.proxmox.enabled:
        adapters.append(ProxmoxAdapter(services.proxmox))
    if services.uptime_kuma and services.uptime_kuma.enabled:
        adapters.append(UptimeKumaAdapter(services.uptime_kuma))
    if services.whatsupdocker and services.whatsupdocker.enabled:
        adapters.append(WhatsUpDockerAdapter(services.whatsupdocker))
    if services.stirling and services.stirling.enabled:
        adapters.append(StirlingAdapter(services.stirling))
    return adapters


def create_app(config: AppConfig | None = None, *, start_poller: bool = True) -> FastAPI:
    app_config = config or load_config()
    cache = SnapshotCache()
    poller = Poller(
        build_adapters(app_config),
        cache,
        interval_seconds=app_config.poll_interval_seconds,
        timeout_seconds=app_config.timeout_seconds,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.config = app_config
        app.state.cache = cache
        app.state.poller = poller
        if start_poller:
            await poller.start()
        try:
            yield
        finally:
            await poller.stop()

    app = FastAPI(title="Miniparser", version=__version__, lifespan=lifespan)
    app.state.config = app_config
    app.state.cache = cache
    app.state.poller = poller

    @app.get("/healthz")
    async def healthz() -> dict[str, int | str]:
        return {"status": "ok", "services": len(poller.adapters)}

    @app.post("/api/v1/refresh", dependencies=[Depends(require_esp_token)])
    async def refresh(request: Request) -> dict[str, str]:
        await request.app.state.poller.refresh_once()
        return {"status": "ok"}

    @app.get("/api/v1/esp", dependencies=[Depends(require_esp_token)])
    async def esp_snapshot(request: Request) -> JSONResponse:
        payload = await request.app.state.cache.payload()
        status_code = status.HTTP_200_OK if await request.app.state.cache.has_any_success() else status.HTTP_503_SERVICE_UNAVAILABLE
        return JSONResponse(payload, status_code=status_code)

    return app


async def require_esp_token(request: Request) -> None:
    expected = request.app.state.config.esp_token
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="ESP_BEARER_TOKEN is not configured")

    supplied = None
    authorization = request.headers.get("authorization")
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    supplied = supplied or request.query_params.get("token")

    if supplied != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


app = create_app()
