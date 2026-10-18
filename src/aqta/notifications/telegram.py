"""Telegram adapter (aiogram 3): notifier, proposal publisher and bot router behind an
allowlisted-user gate (FR-052).

The API process runs the bot with long polling (outbound only, no public webhook), so approvals
share the API's gateway, paper broker and kill switch. Without a token, fakes are used.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message, TelegramObject

from aqta.core.logs import get_logger
from aqta.core.settings import Settings
from aqta.notifications.bot import BotActions, BotController, ProposalCb, Reply, proposal_card
from aqta.notifications.formatter import MAX_SUMMARY_CHARS
from aqta.notifications.ports import FakeNotifier, Notification, NotifierPort
from aqta.proposals import Proposal

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


def build_router(settings: Settings, actions: BotActions | None = None) -> Router:
    """Commands and buttons. Without ``actions`` only /start and /mode answer (dev fallback)."""
    router = Router(name="aqta")
    controller = BotController(actions) if actions is not None else None

    @router.message(Command("start", "help"))
    async def start(message: Message) -> None:
        if controller is None:
            await message.answer(
                f"AQTA online. Mode: {settings.trading_mode.value.upper()}. "
                "Proposals arrive here for approval."
            )
            return
        await _answer(message, controller.help())

    @router.message(Command("mode"))
    async def mode(message: Message) -> None:
        await message.answer(f"Trading mode: {settings.trading_mode.value.upper()}")

    if controller is None:
        return router

    @router.message(Command("status"))
    async def status(message: Message) -> None:
        await _answer(message, await controller.status())

    @router.message(Command("proposals"))
    async def proposals(message: Message) -> None:
        for reply in await controller.proposals():
            await _answer(message, reply)

    @router.message(Command("kill"))
    async def kill(message: Message, command: CommandObject) -> None:
        """FR-034: one command, no code needed, so it always works in an emergency."""
        await _answer(message, await controller.kill(command.args or ""))

    @router.message(Command("release"))
    async def release(message: Message) -> None:
        await _answer(message, controller.release())

    @router.callback_query(ProposalCb.filter())
    async def on_button(query: CallbackQuery, callback_data: ProposalCb) -> None:
        reply = await controller.on_callback(callback_data)
        if isinstance(query.message, Message):
            await query.message.edit_text(reply.text, reply_markup=reply.keyboard)
        await query.answer()

    return router


async def _answer(message: Message, reply: Reply) -> None:
    await message.answer(reply.text, reply_markup=reply.keyboard)


def build_dispatcher(settings: Settings, actions: BotActions | None = None) -> Dispatcher:
    dp = Dispatcher()
    gate = AllowlistMiddleware(settings.telegram_allowed_user_id)
    dp.message.outer_middleware(gate)
    dp.callback_query.outer_middleware(gate)
    dp.include_router(build_router(settings, actions))
    return dp


def build_bot(settings: Settings) -> Bot | None:
    """The bot, or None when Telegram is not configured (then fakes are used)."""
    token = settings.telegram_bot_token
    if token is None or settings.telegram_allowed_user_id is None:
        return None
    return Bot(token=token.get_secret_value())


class TelegramNotifier:
    def __init__(self, bot: Any, chat_id: int) -> None:
        self._bot = bot
        self._chat_id = chat_id

    async def send(self, notification: Notification) -> None:
        text = notification.text
        if notification.kind == "trade_summary" and len(text) > MAX_SUMMARY_CHARS:
            raise ValueError("trade summaries must be <= 600 chars (FR-044)")
        await self._bot.send_message(self._chat_id, text)


class TelegramProposalPublisher:
    """Sends each new pending proposal to Kashyap's chat as a card with buttons (FR-023)."""

    def __init__(self, bot: Any, chat_id: int, mode: str) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._mode = mode

    async def publish(self, proposal: Proposal) -> None:
        reply = proposal_card(proposal, self._mode)
        await self._bot.send_message(self._chat_id, reply.text, reply_markup=reply.keyboard)


class FakeProposalPublisher:
    def __init__(self) -> None:
        self.published: list[Proposal] = []

    async def publish(self, proposal: Proposal) -> None:
        self.published.append(proposal)


def build_notifier(settings: Settings, bot: Any | None = None) -> NotifierPort:
    bot = bot if bot is not None else build_bot(settings)
    chat_id = settings.telegram_allowed_user_id
    if bot is None or chat_id is None:
        log.info("notify.using_fake", reason="TELEGRAM_BOT_TOKEN or allowed user id not set")
        return FakeNotifier()
    return TelegramNotifier(bot, chat_id)


def build_publisher(
    settings: Settings, bot: Any | None
) -> TelegramProposalPublisher | FakeProposalPublisher:
    chat_id = settings.telegram_allowed_user_id
    if bot is None or chat_id is None:
        return FakeProposalPublisher()
    return TelegramProposalPublisher(bot, chat_id, settings.trading_mode.value)
