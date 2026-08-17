"""Dedicated NEXUS Gateway application.

This package is the *application* layer for external communication gateways
(Telegram, Discord, WhatsApp, Slack, Signal, webhooks, ...). It does not
re-implement gateway logic — the engine lives in the top-level ``gateways``
package (``gateways.GatewaySupervisor``, ``gateways.GatewayRunner``, platform
adapters, webhook server). This application:

* discovers enabled gateways (env-gated, via the engine),
* supervises their connections and health,
* reconnects failed gateways with backoff,
* routes inbound messages into the central command bus when available,
* preserves per-chat session mappings,
* and shuts down gracefully.

The engine remains the single source of truth for gateway behaviour; this
layer only orchestrates it (architecture spec section 2.10 / 5 / 20).
"""

from .application import GatewayApplication
from .lifecycle import GatewayAppState

__all__ = ["GatewayApplication", "GatewayAppState"]
