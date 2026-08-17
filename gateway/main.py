"""
NEXUS Unified Gateway Commander.
Launches all platform adapters under the supervised GatewaySupervisor + an
optional Meta webhook server.

The supervisor reconnects failed platforms with exponential backoff, disables
crash-looping adapters with a cooldown, and persists lifecycle state to
~/.nexus/gateway/state.json so a disabled platform is honoured across restarts.
GatewayRunner remains available for programs that want plain connect/disconnect;
this entry point uses the supervised runtime.
"""

import asyncio
import logging
import os

from gateway.supervisor import GatewaySupervisor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("NEXUS-GATEWAY")


async def main():
    logger.info("Initializing Unified Gateway Commander...")

    runner = GatewaySupervisor()
    runner.register_all()

    logger.info("Launching all active intelligence gateways...")

    # Start the supervised gateway runner in a task.
    gateway_task = asyncio.create_task(runner.run())

    # Start the lightweight webhook server to receive inbound messages from any
    # configured platform (Meta/WhatsApp, LINE, Teams, Feishu, WeCom, Weixin,
    # YuanBao, QQBot, DingTalk, Google Chat, BlueBubbles). Each platform's route
    # is registered only when that platform's env credentials are present,
    # which webhook_server.build_platform_routes enforces per route.
    verify_token = os.getenv("META_VERIFY_TOKEN", "")
    try:
        if runner.adapters:
            try:
                from gateway.webhook_server import start_webhook_server
                webhook_task = asyncio.create_task(
                    start_webhook_server(runner.adapters, verify_token)
                )
                logger.info("Webhook server started on port 8080.")
                await asyncio.gather(gateway_task, webhook_task)
            except ImportError:
                logger.warning(
                    "webhook_server module not found — inbound webhooks not available."
                )
                await gateway_task
        else:
            await gateway_task
    finally:
        # Graceful shutdown: cancel tasks, await disconnects, flush lifecycle state.
        try:
            from gateway.webhook_server import stop_webhook_server
            await stop_webhook_server()
        except Exception:  # degrade softly on shutdown
            logger.warning("gateway/main.py webhook stop suppressed error", exc_info=True)
        try:
            await runner.stop_all()
        except Exception:  # degrade softly on shutdown
            logger.warning("gateway/main.py stop_all suppressed error", exc_info=True)


def run():
    asyncio.run(main())


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        logger.info("Gateway shutdown initiated by user.")
