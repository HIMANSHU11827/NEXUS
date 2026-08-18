# integrations — External integrations (messaging, MCP, plugins, providers)

## Authoritative implementation
- `gateways/` — 21-platform messaging gateway (Telegram, Discord, WhatsApp, Slack, Signal, plus `platforms/`), `main.py`/`run.py` entry points, `supervisor.py`, `delivery.py`
- `extensions/mcp/core/` — MCP stdio client/server integration (`client.py`, `server.py`, `tool/`), `security.py`
- `extensions/plugins/built_in/` — plugin system with lifecycle hooks and trust model (`manager.py`, `trust.py`)
- `models/providers/` — 40+ LLM provider implementations under `core/`, `api/`, `auth/`, `local/`

## Why this directory exists
This is the approved home for external-integration ownership. The implementations live in `gateways/`, `extensions/mcp/core/`, `extensions/plugins/built_in/`, and `models/providers/`; `integrations/` holds the responsibility map.

## Notes
Run the gateway with `python -m nexus --gateway`.