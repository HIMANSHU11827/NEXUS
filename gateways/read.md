# NEXUS Gateway

Multi-platform messaging gateway — routes messages between NEXUS AI and external platforms.

**Version:** 2.0.0

## Platforms
21 async platform adapters: BlueBubbles, DingTalk, Discord, Email, Feishu, Google Chat, IRC, LINE, Matrix, Mattermost, Meta (Facebook/Instagram), QQBot, Signal, Slack, SMS, Teams, Telegram, WeCom, Weixin, WhatsApp, Yuanbao.

## Structure
- `base.py` — `BasePlatformAdapter` ABC + `MessageEvent` / `SendResult` dataclasses, lifecycle state constants, shared polling guard with exponential backoff
- `run.py` — `GatewayRunner`: env-var gated auto-registration, ingress dedupe, per-chat `NexusLoop` instances with streaming responses
- `supervisor.py` — `GatewaySupervisor` + `PlatformRuntime`: supervised lifecycle (connect retries, crash-loop detection, state persistence, graceful stop)
- `main.py` — Unified Gateway Commander entry point (supervisor + webhook server)
- `state.py` — `GatewayStateStore`: atomic JSON persistence to `~/.nexus/gateway/state.json`
- `platforms/` — Lazy adapter factory for 21 platforms (env-gated registration)
- `webhook_server.py` — aiohttp webhook server (port 8080): Meta (HMAC, fail-closed) + LINE, Teams, Google Chat, Feishu, YuanBao, QQBot, DingTalk, WeCom (encrypted), Weixin, BlueBubbles — routes registered only when credentials exist
- `telegram_bot.py` — legacy polling bot (uses `NexusLoop` directly)
- `session_bus_integration.py` — `GatewaySessionManager`: persistent session tracking with age-based cleanup
- `session_ids.py` — Stable gateway session ID generation
- Legacy `gateway/<platform>/scripts/` files are deprecated — use the async `BasePlatformAdapter` runtime

## Environment
- Telegram: `TELEGRAM_BOT_TOKEN`
- Discord: `DISCORD_BOT_TOKEN`
- Slack: `SLACK_BOT_TOKEN`
- WhatsApp/Meta: `META_ACCESS_TOKEN`, `META_VERIFY_TOKEN`, `META_PHONE_NUMBER_ID`
- Signal: `SIGNAL_NUMBER`
