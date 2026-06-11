import httpx

from app.adapters import ImmichAdapter, ProxmoxAdapter, StirlingAdapter, WhatsUpDockerAdapter
from app.config import ImmichConfig, ProxmoxConfig, StirlingConfig, WhatsUpDockerConfig


def mock_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test")


async def test_immich_adapter_maps_statistics(monkeypatch):
    monkeypatch.setenv("IMMICH_API_KEY", "key")

    def handler(request):
        assert request.headers["x-api-key"] == "key"
        return httpx.Response(
            200,
            json={"users": 2, "photos": 10, "videos": 3, "usage": 1024},
        )

    async with mock_client(handler) as client:
        payload = await ImmichAdapter(ImmichConfig(url="http://immich.local")).fetch(client)

    assert payload == {
        "imm_users": 2,
        "imm_photos": 10,
        "imm_videos": 3,
        "imm_storage": 1024,
    }


async def test_proxmox_adapter_counts_resources(monkeypatch):
    monkeypatch.setenv("PROXMOX_TOKEN_ID", "root@pam!desk")
    monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "secret")

    def handler(request):
        assert request.headers["authorization"] == "PVEAPIToken=root@pam!desk=secret"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"type": "node", "cpu": 0.25, "mem": 4, "maxmem": 8},
                    {"type": "node", "cpu": 0.75, "mem": 2, "maxmem": 8},
                    {"type": "qemu"},
                    {"type": "lxc"},
                    {"type": "lxc"},
                ]
            },
        )

    async with mock_client(handler) as client:
        payload = await ProxmoxAdapter(ProxmoxConfig(url="https://pve.local:8006")).fetch(client)

    assert payload["pve_vms"] == 1
    assert payload["pve_lxc"] == 2
    assert payload["pve_cpu"] == 50
    assert payload["pve_mem"] == 37.5


async def test_whatsupdocker_adapter_counts_updates(monkeypatch):
    monkeypatch.setenv("WUD_TOKEN", "token")

    def handler(request):
        assert request.headers["authorization"] == "Bearer token"
        return httpx.Response(
            200,
            json=[
                {"name": "a", "updateAvailable": True},
                {"name": "b", "updateAvailable": False},
            ],
        )

    async with mock_client(handler) as client:
        payload = await WhatsUpDockerAdapter(WhatsUpDockerConfig(url="http://wud.local")).fetch(client)

    assert payload == {"wud_monitoring": 2, "wud_updates": 1}


async def test_stirling_adapter_reports_latency():
    def handler(request):
        return httpx.Response(200, text="ok")

    async with mock_client(handler) as client:
        payload = await StirlingAdapter(StirlingConfig(url="http://stirling.local")).fetch(client)

    assert payload["st_ok"] is True
    assert payload["st_ms"] >= 0

