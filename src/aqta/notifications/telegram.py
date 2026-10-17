"""Telegram adapter (aiogram 3): notifier + bot router with an allowlisted-user gate (FR-052).

Webhook-ready (the router can be mounted on any Dispatcher); long polling is used in dev via
``python -m aqta.notifications``. Without a token the app falls back to ``FakeNotifier``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message, TelegramObject

from aqta.core.logs import get_logger
from aqta.core.settings import Settings
from aqta.notifications.formatter import MAX_SUMMARY_CHARS
from aqta.notifications.ports import FakeNotifier, Notification, NotifierPort

log = get_logger(__name__)


def is_allowed(user_id: int | None, allowed_user_id: int | None) -> bool:
    return user_id is not None and allowed_user_id is not None and user_id == allowed_user_id


class AllowlistMiddleware(BaseMiddleware):
    """Drops (and logs) every update from anyone but Kashyap's allowlisted account (FR-052)."""

    def __init__(self, allowed_user_id: int | None) -> None:
        self._allowed = allowed_user_id
        self.ignored = 0

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        user_id = getattr(user, "id", None)
        if not is_allowed(user_id, self._allowed):
            self.ignored += 1
            log.warning("telegram.unauthorized_ignored", user_id=user_id)
            return None
        return await handler(event, data)


def build_router(settings: Settings) -> Router:
    router = Router(name="aqta")

    @router.message(Command("start"))
    async def start(message: Message) -> None:
        await message.answer(
            f"AQTA online. Mode: {settings.trading_mode.value.upper()}. "
            "Proposals arrive here for approval."
        )

    @router.message(Command("mode"))
    async def mode(message: Message) -> None:
        await message.answer(f"Trading mode: {settings.trading_mode.value.upper()}")

    # TODO(FR-023, FR-034, NFR-017): approve/reject/modify inline buttons and /kill command.
    return router


def build_dispatcher(settings: Settings) -> Dispatcher:
    dp = Dispatcher()
    gate = AllowlistMiddleware(settings.telegram_allowed_user_id)
    dp.message.outer_middleware(gate)
    dp.callback_query.outer_middleware(gate)
    dp.include_router(build_router(settings))
    return dp


class TelegramNotifier:
    def __init__(self, bot: Any, chat_id: int) -> None:
        self._bot = bot
        self._chat_id = chat_id

    async def send(self, notification: Notification) -> None:
        text = notification.text
        if notification.kind == "trade_summary" and len(text) > MAX_SUMMARY_CHARS:
            raise ValueError("trade summaries must be <= 600 chars (FR-044)")
        await self._bot.send_message(self._chat_id, text)


def build_notifier(settings: Settings) -> NotifierPort:
    token = settings.telegram_bot_token
    chat_id = settings.telegram_allowed_user_id
    if token is None or chat_id is None:
        log.info("notify.using_fake", reason="TELEGRAM_BOT_TOKEN or allowed user id not set")
        return FakeNotifier()
    return TelegramNotifier(Bot(token=token.get_secret_value()), chat_id)
