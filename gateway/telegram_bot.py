"""
NEXUS TELEGRAM MESSAGING GATEWAY (PORT FROM HERMES-AGENT)
Enables remote God-Architect control of NEXUS OS via Telegram.
Architecture: Async Event Loop + Persistent Architect Session.
"""

import asyncio
import logging
import os

try:
    from telebot.async_telebot import AsyncTeleBot
except Exception:  # pragma: no cover - optional dependency
    AsyncTeleBot = None  # type: ignore[assignment]

from orchestrators.loop import NexusLoop

# Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_IDS = [int(x) for x in os.getenv("ALLOWED_TELEGRAM_IDS", "").split(",") if x]

# NEXUS Kernel
loop = NexusLoop()

bot = AsyncTeleBot(TELEGRAM_TOKEN) if (TELEGRAM_TOKEN and AsyncTeleBot is not None) else None


async def send_welcome(message):
    if message.from_user.id not in ALLOWED_USER_IDS:
        return
    status = f"NEXUS OS v6.2 [ONLINE]\nKernel: NexusLoop\nUptime: Active\nCWD: {loop.root}"
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
        async for chunk in loop.stream_run(task_desc):
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
