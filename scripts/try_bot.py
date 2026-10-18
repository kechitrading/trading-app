"""Try the Telegram bot on your PC with a sample proposal (paper mode, nothing stored).

Usage (from the aqta folder):  .venv\\Scripts\\python.exe scripts\\try_bot.py

Uses your .env for TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_USER_ID, but keeps everything else in
memory: no Postgres, Redis or Docker needed, and nothing is written anywhere. Paper mode only, so
no order can reach Angel One. Press Ctrl+C to stop.

Only one process may poll a bot token at a time, so stop this before the server runs the bot.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from datetime import timedelta
from decimal import Decimal

from aqta.api import build_in_memory_container
from aqta.api.app import start_bot, stop_bot
from aqta.core.clock import Clock, SystemClock
from aqta.core.ids import new_id
from aqta.core.settings import AppEnv, TradingMode, load_settings
from aqta.core.trading import (
    Exchange,
    Instrument,
    OrderRequest,
    RiskEffect,
    Segment,
    Side,
)
from aqta.proposals import Horizon, Proposal, ProposalStatus

LOT = 75  # NIFTY lot size used for the sample; prices are illustrative, not market data


def sample_proposal(clock: Clock, minutes: int = 5) -> Proposal:
    """2 sets of: buy 1 lot NIFTY futures, protected by 1 lot of bought puts (hedge first)."""
    pid = new_id("prop")
    fut = Instrument(
        symbol="NIFTY-FUT-SAMPLE", exchange=Exchange.NSE, segment=Segment.FUT, lot_size=LOT
    )
    put = Instrument(
        symbol="NIFTY-24800PE-SAMPLE", exchange=Exchange.NSE, segment=Segment.OPT, lot_size=LOT
    )
    legs = (
        OrderRequest(
            client_order_id=f"{pid}_l1",
            proposal_id=pid,
            instrument=fut,
            side=Side.BUY,
            quantity=2 * LOT,
            limit_price=Decimal("25000"),
            reference_price=Decimal("25000"),
            max_loss_inr=Decimal("4000"),
            margin_required_inr=Decimal("250000"),
        ),
        OrderRequest(
            client_order_id=f"{pid}_l2",
            proposal_id=pid,
            instrument=put,
            side=Side.BUY,
            quantity=2 * LOT,
            limit_price=Decimal("60"),
            reference_price=Decimal("60"),
            risk_effect=RiskEffect.REDUCING,
            max_loss_inr=Decimal("9000"),
            margin_required_inr=Decimal("9000"),
        ),
    )
    now = clock.now()
    return Proposal(
        id=pid,
        created_at=now,
        valid_until=now + timedelta(minutes=minutes),
        horizon=Horizon.INTRADAY,
        underlying="NIFTY (SAMPLE)",
        legs=legs,
        max_loss_inr=Decimal("13000"),
        margin_required_inr=Decimal("259000"),
        return_on_margin=Decimal("0.0300"),
        status=ProposalStatus.PENDING_APPROVAL,
        rationale={"note": "Sample proposal from scripts/try_bot.py; not a trade idea."},
    )


async def main() -> int:
    settings = load_settings().model_copy(update={"app_env": AppEnv.DEV, "telegram_polling": True})
    if settings.trading_mode is not TradingMode.PAPER:
        print("Refusing to run: TRADING_MODE must be paper for this trial.")  # noqa: T201
        return 1
    if settings.telegram_bot_token is None or settings.telegram_allowed_user_id is None:
        print("Set TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_USER_ID in .env first.")  # noqa: T201
        return 1

    container = build_in_memory_container(settings, SystemClock())
    poller = start_bot(container)
    try:
        await container.proposals.submit(sample_proposal(container.clock))
        print(  # noqa: T201
            "Bot running in PAPER mode with in-memory storage.\n"
            "A sample proposal was sent to your Telegram chat. Try Approve, Reject, Smaller,\n"
            "/proposals, /status and /kill test. Press Enter here to send another sample,\n"
            "or Ctrl+C to stop."
        )
        while True:
            await asyncio.to_thread(sys.stdin.readline)
            await container.proposals.submit(sample_proposal(container.clock))
            print("Sent another sample proposal.")  # noqa: T201
    finally:
        await stop_bot(poller)
        await container.close()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        raise SystemExit(asyncio.run(main()))
