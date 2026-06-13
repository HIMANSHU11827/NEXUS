"""
NEXUS Unified Gateway Commander.
Launches all platform adapters + an optional Meta webhook server.
"""

import asyncio
import logging
import os
from gateway.run import GatewayRunner
from gateway.platforms.telegram import TelegramAdapter
from gateway.platforms.discord import DiscordAdapter
from gateway.platforms.whatsapp import WhatsAppAdapter

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("NEXUS-GATEWAY")


async def main():
    logger.info("Initializing Unified Gateway Commander...")

    runner = GatewayRunner()

    # Telegram
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if tg_token:
        runner.add_adapter(TelegramAdapter(tg_token))
        logger.info("Telegram adapter queued.")

    # Discord
    ds_token = os.getenv("DISCORD_BOT_TOKEN")
    if ds_token:
        runner.add_adapter(DiscordAdapter(ds_token))
        logger.info("Discord adapter queued.")

    # Meta (FB / IG / WA)
    meta_token = os.getenv("META_ACCESS_TOKEN")
    verify_token = os.getenv("META_VERIFY_TOKEN", "")
    if meta_token:
        from gateway.platforms.meta import MetaAdapter
        runner.add_adapter(MetaAdapter("facebook", meta_token, verify_token))
        runner.add_adapter(MetaAdapter("instagram", meta_token, verify_token))
        runner.add_adapter(WhatsAppAdapter(meta_token, verify_token))
        logger.info("Meta (FB/IG/WA) adapters queued.")

    logger.info("Launching all active intelligence gateways...")

    # Start the gateway runner in a task
    gateway_task = asyncio.create_task(runner.run())

    # If Meta tokens exist, start a lightweight webhook server for Meta webhooks
    if meta_token:
        try:
            from gateway.webhook_server import start_webhook_server
            runner_instances = {p: a for p, a in runner.adapters.items() if p in ("facebook", "instagram", "whatsapp")}
            webhook_task = asyncio.create_task(start_webhook_server(runner_instances, verify_token))
            logger.info("Meta webhook server started on port 8080.")
            await asyncio.gather(gateway_task, webhook_task)
        except ImportError:
            logger.warning("webhook_server module not found — Meta webhooks not available.")
            await gateway_task
    else:
        await gateway_task


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Gateway shutdown initiated by user.")
