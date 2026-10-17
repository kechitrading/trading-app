from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from aqta.core.settings import Settings
from aqta.notifications import (
    MAX_SUMMARY_CHARS,
    AllowlistMiddleware,
    EmailNotifier,
    FakeNotifier,
    Notification,
    TelegramNotifier,
    TradeEvent,
    TradeEventKind,
    build_dispatcher,
    build_notifier,
    format_summary,
    is_allowed,
)

AT = datetime(2026, 10, 20, 4, 30, tzinfo=UTC)


def event(**kw: Any) -> TradeEvent:
    data: dict[str, Any] = {
        "kind": TradeEventKind.PROPOSAL,
        "mode": "paper",
        "at": AT,
        "proposal_id": "prop_1",
        "symbol": "NIFTY 25000 CE",
        "side": "BUY",
        "quantity": 75,
        "price": Decimal("120.5"),
        "max_loss_inr": Decimal("9037.5"),
        "margin_inr": Decimal("9037.5"),
        "valid_until": AT + timedelta(minutes=5),
    }
    data.update(kw)
    return TradeEvent(**data)


def test_summary_contents_and_mode_label() -> None:
    text = format_summary(event())
    assert text.startswith("[PAPER] PROPOSAL NIFTY 25000 CE")
    assert "BUY 75 @ 120.5" in text
    assert "max loss Rs 9,038" in text
    assert "valid until 10:05 IST" in text
    assert "Proposal only" in text
    fill = format_summary(
        event(
            kind=TradeEventKind.EXIT,
            mode="live",
            pnl_inr=Decimal("-1500"),
            max_loss_inr=None,
            margin_inr=None,
            valid_until=None,
        )
    )
    assert fill.startswith("[LIVE] EXIT") and "P&L Rs -1,500" in fill
    assert "Proposal only" not in fill


@pytest.mark.parametrize("note_len", [0, 300, 590, 5000])
def test_summary_never_exceeds_600_chars(note_len: int) -> None:
    text = format_summary(event(note="x" * note_len))
    assert len(text) <= MAX_SUMMARY_CHARS
    if note_len >= 590:
        assert text.endswith("…")


def test_allowlist() -> None:
    assert is_allowed(42, 42)
    assert not is_allowed(7, 42)
    assert not is_allowed(None, 42)
    assert not is_allowed(42, None)


async def test_allowlist_middleware_ignores_unlisted_users() -> None:
    gate = AllowlistMiddleware(allowed_user_id=42)
    calls: list[int] = []

    async def handler(evt: Any, data: dict[str, Any]) -> str:
        calls.append(evt.from_user.id)
        return "handled"

    assert await gate(handler, SimpleNamespace(from_user=SimpleNamespace(id=42)), {}) == "handled"
    assert await gate(handler, SimpleNamespace(from_user=SimpleNamespace(id=666)), {}) is None
    assert await gate(handler, SimpleNamespace(), {}) is None
    assert calls == [42] and gate.ignored == 2


async def test_build_notifier_falls_back_to_fake(settings: Settings) -> None:
    notifier = build_notifier(settings)
    assert isinstance(notifier, FakeNotifier)
    await notifier.send(Notification("hello"))
    assert notifier.sent[0].text == "hello"
    real = build_notifier(
        settings.model_copy(
            update={
                "telegram_bot_token": SecretStr("123456:" + "A" * 35),
                "telegram_allowed_user_id": 42,
            }
        )
    )
    assert isinstance(real, TelegramNotifier)
    assert build_dispatcher(settings) is not None


async def test_telegram_notifier_sends_to_allowlisted_chat() -> None:
    sent: list[tuple[int, str]] = []

    class FakeBot:
        async def send_message(self, chat_id: int, text: str) -> None:
            sent.append((chat_id, text))

    notifier = TelegramNotifier(FakeBot(), chat_id=42)
    await notifier.send(Notification(format_summary(event()), kind="trade_summary"))
    assert sent[0][0] == 42
    with pytest.raises(ValueError, match="600"):
        await notifier.send(Notification("x" * 601, kind="trade_summary"))


async def test_email_stub() -> None:
    with pytest.raises(NotImplementedError, match="FR-045"):
        await EmailNotifier().send(Notification("report"))
