import httpx

from app.config import AppConfig
from app.main import create_app


def api_client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_esp_endpoint_requires_configured_token(monkeypatch):
    monkeypatch.delenv("ESP_BEARER_TOKEN", raising=False)
    app = create_app(AppConfig(), start_poller=False)

    async with api_client(app) as client:
        response = client.get("/api/v1/esp")
        response = await response

    assert response.status_code == 503
    assert response.json()["detail"] == "ESP_BEARER_TOKEN is not configured"


async def test_esp_endpoint_rejects_bad_token(monkeypatch):
    monkeypatch.setenv("ESP_BEARER_TOKEN", "secret")
    app = create_app(AppConfig(), start_poller=False)

    async with api_client(app) as client:
        response = await client.get("/api/v1/esp", headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_esp_endpoint_accepts_query_token(monkeypatch):
    monkeypatch.setenv("ESP_BEARER_TOKEN", "secret")
    app = create_app(AppConfig(), start_poller=False)

    async with api_client(app) as client:
        response = await client.get("/api/v1/esp?token=secret")

    assert response.status_code == 503
    assert response.json()["ts"] > 0


async def test_healthz_reports_adapter_count(monkeypatch):
    monkeypatch.setenv("ESP_BEARER_TOKEN", "secret")
    config = AppConfig.model_validate(
        {
            "services": {
                "stirling": {"enabled": True, "url": "http://stirling.local:8080"},
                "immich": {"enabled": False, "url": "http://immich.local:2283"},
            }
        }
    )
    app = create_app(config, start_poller=False)

    async with api_client(app) as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["services"] == 1
