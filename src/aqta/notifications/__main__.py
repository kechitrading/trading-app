"""Dev runner: ``python -m aqta.notifications`` starts the bot with long polling."""

from __future__ import annotations

import asyncio

from aiogram import Bot

from aqta.core.logs import configure_logging, get_logger
from aqta.core.settings import get_settings
from aqta.notifications.telegram import build_dispatcher


async def _run() -> int:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    log = get_logger("aqta.bot")
    if settings.telegram_bot_token is None:
        log.warning("bot.disabled", reason="TELEGRAM_BOT_TOKEN not set; using fake notifier only")
        return 0
    bot = Bot(token=settings.telegram_bot_token.get_secret_value())
    await build_dispatcher(settings).start_polling(bot)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
