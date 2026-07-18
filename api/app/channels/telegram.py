"""Telegram interface: long-polling bot locked to the owner's chat id.

Every text message is routed into the LangGraph chat agent; the agent's reply
comes back to the same chat. Non-owner chats are dropped by a hard filter.
"""

import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from app.config import get_settings

logger = logging.getLogger(__name__)

# Telegram messages are capped at 4096 chars.
TELEGRAM_MAX_LEN = 4000


def chunk_text(text: str, limit: int = TELEGRAM_MAX_LEN) -> list[str]:
    """Split text into Telegram-sized chunks, preferring newline boundaries."""
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 1, limit + 1)
        if cut == -1:
            cut = limit
        else:
            cut += 1  # keep the newline with the leading chunk
        chunks.append(text[:cut])
        text = text[cut:]
    chunks.append(text)
    return chunks


async def send_chunked(bot, chat_id: int, text: str) -> None:
    for chunk in chunk_text(text):
        await bot.send_message(chat_id=chat_id, text=chunk)


async def notify_owner(text: str) -> None:
    """Send a chunked message to the owner with a one-shot Bot.

    Uses `async with` so the Bot's httpx connection pool is shut down afterwards —
    a bare `Bot(...)` eagerly opens pools that are never reclaimed, leaking sockets
    on every digest / reminder / workflow notification in this long-lived process.
    """
    from telegram import Bot

    settings = get_settings()
    async with Bot(settings.telegram_bot_token) as bot:
        await send_chunked(bot, settings.telegram_chat_id, text)


async def _start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "⚡ rotom online. Talk to me — try 'check my emails' or ask about recent mail."
    )


async def _handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from app.agent.graph import run_agent  # late import: avoid LLM init at module load

    text = update.message.text or ""
    await update.effective_chat.send_action(ChatAction.TYPING)
    try:
        reply = await run_agent(text, thread_id=str(update.effective_chat.id))
    except Exception:
        logger.exception("Agent failed handling message")
        reply = "⚠ Something went wrong handling that — check the logs."
    for chunk in chunk_text(reply):
        await update.message.reply_text(chunk)


def create_bot_app() -> Application:
    settings = get_settings()
    owner_filter = filters.Chat(chat_id=settings.telegram_chat_id)
    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", _start, filters=owner_filter))
    app.add_handler(MessageHandler(owner_filter & filters.TEXT & ~filters.COMMAND, _handle_message))
    return app
