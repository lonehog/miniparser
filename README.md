# Miniparser

Miniparser is a small Docker service for desk displays and ESP32 monitors. It polls homelab apps in the background, keeps a cached snapshot, and exposes compact JSON through one authenticated endpoint.

## Quick Start

```bash
cp config.example.yml config.yml
cp .env.example .env
docker compose --env-file .env -f docker-compose.example.yml up --build
```

Set `ESP_BEARER_TOKEN` in `.env`, then fetch:

```bash
curl -H "Authorization: Bearer change-me" http://127.0.0.1:8080/api/v1/esp
```

For simple ESP32 firmware, the token can also be passed as a query parameter:

```text
http://miniparser.local:8080/api/v1/esp?token=change-me
```

## Configuration

Mount a YAML config at `/config/config.yml` and put sensitive values in environment variables. `config.example.yml` contains all supported v1 services:

- Glances
- Immich
- Komodo
- Proxmox
- Uptime Kuma
- What's Up Docker
- Stirling PDF health check

Disable any integration with `enabled: false`.

If no config file is present, Miniparser starts with zero integrations so the container remains reachable while you fix the mount.

## ESP32 Payload

`GET /api/v1/esp` returns flat keys to keep parsing cheap:

```json
{
  "ts": 1718121200,
  "g_ok": true,
  "g_cpu": 12.5,
  "g_mem": 48.1,
  "imm_ok": true,
  "imm_photos": 12345,
  "kuma_down": 0
}
```

Each service also emits:

- `*_ok`: last poll status
- `*_age`: seconds since last successful update
- `*_err`: short error message when the last poll failed

If no service has produced a successful result yet, `/api/v1/esp` returns HTTP `503` with whatever status data is available.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
```

Run locally:

```bash
ESP_BEARER_TOKEN=change-me CONFIG_PATH=config.yml .venv/bin/python -m uvicorn app.main:create_app --factory --reload --port 8080
```
