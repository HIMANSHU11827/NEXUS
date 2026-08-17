# NEXUS Gateway Application

Dedicated application that starts and supervises NEXUS external communication
gateways (Telegram, Discord, WhatsApp, Slack, Signal, webhooks, …).

## What it does

- **Discovers** enabled gateways (env-gated, via the `gateways` engine).
- **Validates** gateway metadata and configuration.
- **Starts** each platform connection under a supervised runtime.
- **Supervises** health and **reconnects** failed gateways with backoff and a
  crash-loop cooldown (handled by the engine's `GatewaySupervisor`).
- **Routes** inbound messages into the central command bus when available
  (`nexus.commands`), preserving the "one central command system" rule.
- **Preserves** per-chat session mappings.
- **Shuts down** gracefully (cancels supervision, flushes lifecycle state).

## Architecture note

This package is the **application layer only**. All gateway behaviour lives in
the top-level `gateways/` package (`GatewaySupervisor`, `GatewayRunner`,
platform adapters, webhook server). This app orchestrates that engine; it does
not re-implement it.

## Usage

```bash
python -m apps.gateway.nexus_gateway_app
# or, after install:
nexus-gateway-app
```

Set platform credentials via environment variables (e.g. `TELEGRAM_BOT_TOKEN`)
as documented in `gateways/`. No enabled gateway → the app starts in degraded
mode and idles safely rather than crashing.
