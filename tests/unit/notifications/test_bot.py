from __future__ import annotations

import asyncio
from typing import Any

import pytest
from aiogram import Dispatcher
from aiogram.types import InlineKeyboardMarkup

from aqta.api import Container, build_in_memory_container
from aqta.api.actions import ContainerBotActions
from aqta.api.app import start_bot, stop_bot
from aqta.core.clock import FrozenClock
from aqta.core.settings import Settings, TradingMode
from aqta.notifications import (
    BotController,
    FakeProposalPublisher,
    ProposalCb,
    TelegramProposalPublisher,
    build_dispatcher,
    format_proposal,
    proposal_card,
)
from aqta.proposals import ProposalStatus
from factories import make_proposal


@pytest.fixture
def container(settings: Settings, clock: FrozenClock) -> Container:
    return build_in_memory_container(settings, clock)


@pytest.fixture
def bot(container: Container) -> BotController:
    return BotController(ContainerBotActions(container))


def buttons(kb: InlineKeyboardMarkup | None) -> list[tuple[str, ProposalCb]]:
    assert kb is not None
    return [
        (b.text, ProposalCb.unpack(b.callback_data or ""))
        for row in kb.inline_keyboard
        for b in row
    ]


def cb(action: str, pid: str, sets: int = 0) -> ProposalCb:
    return ProposalCb(action=action, pid=pid, sets=sets)


def test_card_text_and_buttons(clock: FrozenClock) -> None:
    p = make_proposal(clock, lots=(4, 2))
    text = format_proposal(p, "paper")
    assert text.startswith("[PAPER] PROPOSAL NIFTY - intraday")
    assert "1. BUY 4 lot(s) NIFTY26OCTFUT (NSE, qty 300) @ 25000" in text
    assert "2. SELL 2 lot(s) NIFTY26OCT25000CE" in text
    assert "Max loss Rs 6,000 | Margin Rs 120,000 | RoM 5.0%" in text
    assert "Size: 2 set(s) | Valid until 10:05 IST" in text
    assert "Proposal only" in text and p.id in text
    labels = [(t, c.action) for t, c in buttons(proposal_card(p, "paper").keyboard)]
    assert labels == [("Approve", "a"), ("Reject", "r"), ("Smaller", "m")]
    for _, c in buttons(proposal_card(p, "paper").keyboard):
        assert len(c.pack().encode()) <= 64  # Telegram limit


def test_single_set_has_no_smaller_and_closed_card_has_no_buttons(clock: FrozenClock) -> None:
    p = make_proposal(clock, lots=(3, 2))
    assert [c.action for _, c in buttons(proposal_card(p, "paper").keyboard)] == ["a", "r"]
    done = p.model_copy(update={"status": ProposalStatus.REJECTED})
    assert proposal_card(done, "paper").keyboard is None


async def test_new_proposals_are_published(container: Container, clock: FrozenClock) -> None:
    p = await container.proposals.submit(make_proposal(clock))
    assert isinstance(container.publisher, FakeProposalPublisher)
    assert [x.id for x in container.publisher.published] == [p.id]


async def test_publisher_failure_does_not_undo_submit(
    container: Container, clock: FrozenClock
) -> None:
    async def broken(_: Any) -> None:
        raise ConnectionError("telegram down")

    container.proposals.on_new_pending(broken)
    p = await container.proposals.submit(make_proposal(clock))
    assert (await container.proposals.get(p.id)).status is ProposalStatus.PENDING_APPROVAL


async def test_approve_takes_two_taps_and_fills_on_paper(
    bot: BotController, container: Container, clock: FrozenClock
) -> None:
    p = await container.proposals.submit(make_proposal(clock, lots=(2, 2)))
    first = await bot.on_callback(cb("a", p.id))
    assert first.text.endswith("Approve this proposal?")
    assert [c.action for _, c in buttons(first.keyboard)] == ["ac", "b"]
    assert (await container.proposals.get(p.id)).status is ProposalStatus.PENDING_APPROVAL

    done = await bot.on_callback(cb("ac", p.id))
    assert "APPROVED" in done.text and "Paper orders filled." in done.text
    assert done.text.count(": filled") == 2 and done.keyboard is None
    assert (await container.proposals.get(p.id)).status is ProposalStatus.EXECUTED

    again = await bot.on_callback(cb("ac", p.id))
    assert again.text.startswith("Could not do that") and "executed" in again.text


async def test_approve_blocked_leg_shows_reason(
    bot: BotController, container: Container, clock: FrozenClock
) -> None:
    p = await container.proposals.submit(make_proposal(clock))
    await container.kill_switch.trigger("kashyap", "drill")
    done = await bot.on_callback(cb("ac", p.id))
    assert "Stopped at a blocked leg" in done.text and "blocked (kill_switch" in done.text


async def test_back_and_reject(
    bot: BotController, container: Container, clock: FrozenClock
) -> None:
    p = await container.proposals.submit(make_proposal(clock))
    back = await bot.on_callback(cb("b", p.id))
    assert [c.action for _, c in buttons(back.keyboard)] == ["a", "r", "m"]
    rejected = await bot.on_callback(cb("r", p.id))
    assert rejected.text.endswith("REJECTED") and rejected.keyboard is None
    assert (await container.proposals.get(p.id)).status is ProposalStatus.REJECTED


async def test_smaller_offers_sizes_and_replaces_proposal(
    bot: BotController, container: Container, clock: FrozenClock
) -> None:
    p = await container.proposals.submit(make_proposal(clock, lots=(6, 3)))
    assert p.sets == 3
    menu = await bot.on_callback(cb("m", p.id))
    sizes = [(t, c.action, c.sets) for t, c in buttons(menu.keyboard)]
    assert sizes == [("1 set(s)", "ms", 1), ("2 set(s)", "ms", 2), ("Back", "b", 0)]

    replaced = await bot.on_callback(cb("ms", p.id, 1))
    assert "REPLACED by" in replaced.text and replaced.keyboard is None
    assert isinstance(container.publisher, FakeProposalPublisher)
    smaller = container.publisher.published[-1]
    assert smaller.sets == 1 and [leg.lots for leg in smaller.legs] == [2, 1]
    assert (await container.proposals.get(p.id)).status is ProposalStatus.CANCELLED


async def test_expired_proposal_cannot_be_approved(
    bot: BotController, container: Container, clock: FrozenClock
) -> None:
    p = await container.proposals.submit(make_proposal(clock))
    clock.advance(minutes=5)
    reply = await bot.on_callback(cb("ac", p.id))
    assert reply.text.startswith("Could not do that") and "expired" in reply.text
    for action in ("a", "m", "b"):
        closed = await bot.on_callback(cb(action, p.id))
        assert closed.text.endswith("This proposal is expired.") and closed.keyboard is None


async def test_unknown_action_and_missing_proposal(bot: BotController) -> None:
    assert (await bot.on_callback(cb("zz", "prop_x"))).text == "Unknown action."
    assert "not found" in (await bot.on_callback(cb("a", "prop_missing"))).text


async def test_kill_status_release_and_help(
    bot: BotController, container: Container, clock: FrozenClock
) -> None:
    assert "Mode: PAPER" in bot.help().text and "/kill" in bot.help().text
    assert "Kill switch: off" in (await bot.status()).text
    reply = await bot.kill("")
    assert reply.text.startswith("KILL SWITCH ACTIVE") and "0 open order(s)" in reply.text
    assert await container.kill_switch.is_active()
    assert "ACTIVE since" in (await bot.status()).text
    assert "6-digit code" in bot.release().text
    await bot.kill("x")  # short reasons are padded to pass validation
    state = await container.kill_switch.state()
    assert state is not None and state.reason == "Telegram: x"


async def test_proposals_command(
    bot: BotController, container: Container, clock: FrozenClock
) -> None:
    assert [r.text for r in await bot.proposals()] == ["No proposals waiting."]
    p = await container.proposals.submit(make_proposal(clock))
    replies = await bot.proposals()
    assert len(replies) == 1 and p.id in replies[0].text and replies[0].keyboard is not None


async def test_live_mode_approval_sends_no_orders(settings: Settings, clock: FrozenClock) -> None:
    live = settings.model_copy(
        update={"trading_mode": TradingMode.LIVE, "live_trading_enabled": True}
    )
    c = build_in_memory_container(live, clock)
    p = await c.proposals.submit(make_proposal(clock))
    reply = await BotController(ContainerBotActions(c)).on_callback(cb("ac", p.id))
    assert reply.text.startswith("[LIVE]") and "Angel One app" in reply.text
    assert c.gateway.orders == {}


async def test_telegram_publisher_sends_card_with_buttons(clock: FrozenClock) -> None:
    sent: list[dict[str, Any]] = []

    class FakeBot:
        async def send_message(self, chat_id: int, text: str, **kw: Any) -> None:
            sent.append({"chat_id": chat_id, "text": text, **kw})

    p = make_proposal(clock)
    await TelegramProposalPublisher(FakeBot(), 42, "paper").publish(p)
    assert sent[0]["chat_id"] == 42 and p.id in sent[0]["text"]
    assert isinstance(sent[0]["reply_markup"], InlineKeyboardMarkup)


def test_dispatcher_registers_commands_and_buttons(
    settings: Settings, container: Container
) -> None:
    dp = build_dispatcher(settings, ContainerBotActions(container))
    router = dp.sub_routers[0]
    assert len(router.message.handlers) == 6  # start/help, mode, status, proposals, kill, release
    assert len(router.callback_query.handlers) == 1
    bare = build_dispatcher(settings).sub_routers[0]
    assert len(bare.message.handlers) == 2 and len(bare.callback_query.handlers) == 0


async def test_polling_starts_and_stops(
    container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert start_bot(container) is None  # no token configured
    await stop_bot(None)

    started = asyncio.Event()

    async def fake_polling(self: Dispatcher, *bots: Any, **kw: Any) -> None:
        assert kw == {"handle_signals": False, "close_bot_session": False}
        started.set()
        await asyncio.sleep(3600)

    monkeypatch.setattr(Dispatcher, "start_polling", fake_polling)
    container.telegram_bot = object()
    poller = start_bot(container)
    assert poller is not None
    await asyncio.wait_for(started.wait(), 1)
    await stop_bot(poller)
    assert poller[1].done()

    container.settings = container.settings.model_copy(update={"telegram_polling": False})
    assert start_bot(container) is None


async def test_handlers_answer_messages_and_buttons(
    settings: Settings, container: Container, clock: FrozenClock
) -> None:
    from unittest.mock import AsyncMock

    from aiogram.filters import CommandObject
    from aiogram.types import CallbackQuery, Message

    router = build_dispatcher(settings, ContainerBotActions(container)).sub_routers[0]
    handlers = {h.callback.__name__: h.callback for h in router.message.handlers}
    p = await container.proposals.submit(make_proposal(clock))

    def fake_message() -> Any:
        m = AsyncMock(spec=Message)
        m.answer = AsyncMock()
        m.edit_text = AsyncMock()
        return m

    msg = fake_message()
    await handlers["start"](msg)
    await handlers["mode"](msg)
    await handlers["status"](msg)
    await handlers["proposals"](msg)
    await handlers["release"](msg)
    texts = [c.args[0] for c in msg.answer.call_args_list]
    assert texts[0].startswith("AQTA online") and texts[1] == "Trading mode: PAPER"
    assert texts[2].startswith("Mode: PAPER") and p.id in texts[3] and "6-digit" in texts[4]

    await handlers["kill"](msg, CommandObject(command="kill", args="test drill"))
    assert msg.answer.call_args.args[0].startswith("KILL SWITCH ACTIVE")
    assert await container.kill_switch.is_active()

    query = AsyncMock(spec=CallbackQuery)
    query.answer = AsyncMock()
    query.message = fake_message()
    on_button = router.callback_query.handlers[0].callback
    await on_button(query, cb("r", p.id))
    assert query.message.edit_text.call_args.args[0].endswith("REJECTED")
    query.answer.assert_awaited_once()

    bare = {
        h.callback.__name__: h.callback
        for h in build_dispatcher(settings).sub_routers[0].message.handlers
    }
    plain = fake_message()
    await bare["start"](plain)
    assert "Proposals arrive here" in plain.answer.call_args.args[0]
