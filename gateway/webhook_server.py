"""
Lightweight Meta webhook server for WhatsApp / Facebook / Instagram.
Runs alongside the GatewayRunner to receive incoming messages from Meta's Graph API.
"""

import asyncio
import json
import logging
from typing import Dict

from aiohttp import web

logger = logging.getLogger("NEXUS-WEBHOOK")

routes = web.RouteTableDef()
_adapters: Dict[str, object] = {}
_verify_token: str = ""


@routes.get("/webhook/meta")
async def verify(request: web.Request) -> web.Response:
    """Meta webhook verification handshake."""
    mode = request.query.get("hub.mode")
    token = request.query.get("hub.verify_token")
    challenge = request.query.get("hub.challenge")

    if mode == "subscribe" and token == _verify_token:
        logger.info("Meta webhook verified.")
        return web.Response(text=challenge)
    return web.Response(status=403, text="Verification failed")


@routes.post("/webhook/meta")
async def webhook(request: web.Request) -> web.Response:
    """Receive incoming Meta webhook events."""
    try:
        payload = await request.json()
        logger.debug(f"Webhook payload: {json.dumps(payload)[:500]}...")

        for platform, adapter in _adapters.items():
            try:
                if hasattr(adapter, "handle_webhook_payload"):
                    await adapter.handle_webhook_payload(payload)
            except Exception as e:
                logger.error(f"[{platform}] webhook handler error: {e}")

        return web.Response(status=200, text="EVENT_RECEIVED")
    except Exception as e:
        logger.error(f"Webhook parse error: {e}")
        return web.Response(status=400, text="Bad request")


async def start_webhook_server(adapters: Dict[str, object], verify_token: str = "", host: str = "0.0.0.0", port: int = 8080):
    """
    Start the webhook HTTP server.

    Args:
        adapters: Dict mapping platform name -> adapter instance
        verify_token: Meta webhook verification token
        host: Bind address
        port: Listen port
    """
    global _adapters, _verify_token
    _adapters = adapters
    _verify_token = verify_token

    app = web.Application()
    app.add_routes(routes)

    logger.info(f"Meta webhook server listening on {host}:{port}")
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    # Keep running
    while True:
        await asyncio.sleep(3600)
