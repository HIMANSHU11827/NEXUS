"""
NEXUS Unified Gateway Commander.
Launches all platform adapters + an optional Meta webhook server.
"""

import asyncio
import logging
import os

from gateway.run import GatewayRunner

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("NEXUS-GATEWAY")


async def main():
    logger.info("Initializing Unified Gateway Commander...")

    runner = GatewayRunner()
    runner.register_all()

    logger.info("Launching all active intelligence gateways...")

    # Start the gateway runner in a task
    gateway_task = asyncio.create_task(runner.run())

    # If Meta tokens exist, start a lightweight webhook server for Meta webhooks
    meta_adapters = {p: a for p, a in runner.adapters.items() if p in ("facebook", "instagram", "whatsapp", "meta")}
    verify_token = os.getenv("META_VERIFY_TOKEN", "")
    if meta_adapters:
        try:
            from gateway.webhook_server import start_webhook_server
            webhook_task = asyncio.create_task(start_webhook_server(meta_adapters, verify_token))
            logger.info("Meta webhook server started on port 8080.")
            await asyncio.gather(gateway_task, webhook_task)
        except ImportError:
            logger.warning("webhook_server module not found — Meta webhooks not available.")
            await gateway_task
    else:
        await gateway_task


def run():
    asyncio.run(main())


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        logger.info("Gateway shutdown initiated by user.")
