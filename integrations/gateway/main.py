import asyncio
import os
import logging
from integrations.gateway.run import GatewayRunner
from integrations.gateway.platforms.telegram import TelegramAdapter
from integrations.gateway.platforms.discord import DiscordAdapter

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("NEXUS-GATEWAY")

async def main():
    logger.info("⚡ [NEXUS]: Initializing Unified Gateway Commander...")
    
    runner = GatewayRunner()
    
    # 1. Telegram
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if tg_token:
        runner.add_adapter(TelegramAdapter(tg_token))
        logger.info("✅ [TELEGRAM]: Adapter queued.")
    
    # 2. Discord
    ds_token = os.getenv("DISCORD_BOT_TOKEN")
    if ds_token:
        runner.add_adapter(DiscordAdapter(ds_token))
        logger.info("✅ [DISCORD]: Adapter queued.")
    
    # 3. Meta (FB / IG / WA)
    meta_token = os.getenv("META_ACCESS_TOKEN")
    verify_token = os.getenv("META_VERIFY_TOKEN")
    if meta_token:
        from integrations.gateway.platforms.meta import MetaAdapter
        runner.add_adapter(MetaAdapter("facebook", meta_token, verify_token))
        runner.add_adapter(MetaAdapter("instagram", meta_token, verify_token))
        runner.add_adapter(MetaAdapter("whatsapp", meta_token, verify_token))
        logger.info("✅ [META]: FB/IG/WA Adapters queued.")
    
    logger.info("🚀 [NEXUS]: Launching all active intelligence gateways...")
    await runner.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🔌 [GATEWAY]: Shutdown initiated by user.")
