"""
NEXUS TELEGRAM MESSAGING GATEWAY (PORT FROM HERMES-AGENT)
Enables remote God-Architect control of NEXUS OS via Telegram.
Architecture: Async Event Loop + Persistent Architect Session.
"""

import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from telebot.async_telebot import AsyncTeleBot
except Exception:  # pragma: no cover - optional dependency
    AsyncTeleBot = None  # type: ignore[assignment]

from nexus.main_agent import NexusLoop

# Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# Tolerate malformed entries (e.g. `*`) in ALLOWED_TELEGRAM_IDS so a bad env
# value can never crash module import; only numeric user ids are kept.
_ALLOWED_USER_IDS: list = []
for _seg in os.getenv("ALLOWED_TELEGRAM_IDS", "").split(","):
    _seg = _seg.strip()
    if not _seg:
        continue
    try:
        _ALLOWED_USER_IDS.append(int(_seg))
    except (TypeError, ValueError):
        logger.warning("Ignoring non-numeric ALLOWED_TELEGRAM_IDS entry: %r", _seg)
ALLOWED_USER_IDS = _ALLOWED_USER_IDS

# NEXUS Kernel — created lazily so importing this module never crashes when the
# orchestrator API changes (NexusLoop now requires a ``root_dir`` argument).
_loop: Optional[NexusLoop] = None


def get_loop() -> NexusLoop:
    """Return the shared NexusLoop, creating it once on first use."""
    global _loop
    if _loop is None:
        _loop = NexusLoop(root_dir=os.getcwd())
    return _loop


def _valid_telegram_token(value: Optional[str]) -> bool:
    """Avoid constructing the optional client from setup placeholders."""
    token = str(value or "").strip()
    return bool(token and token != "your_telegram_token_here" and ":" in token and not any(ch.isspace() for ch in token))


bot = AsyncTeleBot(TELEGRAM_TOKEN) if (_valid_telegram_token(TELEGRAM_TOKEN) and AsyncTeleBot is not None) else None


async def send_welcome(message):
    if message.from_user.id not in ALLOWED_USER_IDS:
        return
    status = f"NEXUS OS v6.2 [ONLINE]\nKernel: NexusLoop\nUptime: Active\nCWD: {get_loop().root}"
    await bot.reply_to(message, status)


async def handle_task(message):
    if message.from_user.id not in ALLOWED_USER_IDS:
        return

    task_desc = message.text
    await bot.send_chat_action(message.chat.id, "typing")

    # Run the architect coordinate loop
    # Note: For long-running tasks, we stream chunks back to the user
    full_response = ""
    chunk_counter = 0

    await bot.reply_to(message, "🚀 [NEXUS]: Initiating cognitive loop for remote task...")

    try:
        loop = get_loop()
        async for chunk in loop.stream_run(task_desc):
            if isinstance(chunk, dict):
                if chunk.get("type") != "content":
                    continue
                chunk = chunk.get("data") or ""
            full_response += chunk
            chunk_counter += 1

            # Update user every 10 chunks to avoid Telegram rate limits
            if chunk_counter % 15 == 0:
                # We could edit the last message or send new ones
                # For simplicity, we just keep the buffer
                pass

        # Send final result summary
        if len(full_response) > 4000:
            # Split into chunks if too long for Telegram
            for i in range(0, len(full_response), 4000):
                await bot.send_message(message.chat.id, full_response[i:i+4000])
        else:
            await bot.send_message(message.chat.id, full_response)

    except Exception as e:
        await bot.send_message(message.chat.id, f"❌ [KERNEL_ERROR]: {str(e)}")


if bot:
    bot.message_handler(commands=['start', 'status'])(send_welcome)
    bot.message_handler(func=lambda message: True)(handle_task)

async def main():
    if not bot:
        print("TELEGRAM_BOT_TOKEN not found in environment. Remote Gateway inactive.")
        return
    print(f"NEXUS Remote Gateway online. Monitoring for session {ALLOWED_USER_IDS}")
    await bot.infinity_polling()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
