# NEXUS Gateway

Multi-platform messaging gateway — routes messages between NEXUS AI and external platforms.

**Version:** 2.0.0

## Platforms
Discord, Telegram, WhatsApp, Meta (Facebook/Instagram), Slack, Signal, Matrix, Mattermost, Email, SMS — 10 platform adapters.

## Structure
- `base.py` — `BasePlatformAdapter` ABC + `MessageEvent` / `SendResult` dataclasses
- `main.py` / `run.py` — `GatewayRunner`: auto-register platforms via env vars, per-chat NexusLoop instances, streaming response routing
- `platforms/` — Async adapters: `DiscordAdapter`, `TelegramAdapter`, `MetaAdapter`, `SlackAdapter`, `SignalAdapter`, `MatrixAdapter`, `MattermostAdapter`, `EmailAdapter`, `SMSAdapter`
- `webhook_server.py` — aiohttp webhook server (port 8080) for Meta/WhatsApp
- `session_bus_integration.py` — `GatewaySessionManager`: persistent session tracking with age-based cleanup
- `session_ids.py` — Stable gateway session ID generation
- Legacy `gateway/<platform>/scripts/` files are deprecated — use the async `BasePlatformAdapter` runtime

## Environment
- Telegram: `TELEGRAM_BOT_TOKEN`
- Discord: `DISCORD_BOT_TOKEN`
- Slack: `SLACK_BOT_TOKEN`
- WhatsApp/Meta: `META_ACCESS_TOKEN`, `META_VERIFY_TOKEN`, `META_PHONE_NUMBER_ID`
- Signal: `SIGNAL_NUMBER`
