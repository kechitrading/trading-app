"""Telegram approval flow (FR-023, FR-034, FR-052, NFR-017).

Each proposal arrives as a card with buttons. Approving takes two taps (Approve, then Confirm);
rejecting takes one; Smaller offers reduced sizes (reduce-size-only modify). ``/kill`` triggers the
kill switch. Releasing it is not possible here: it loosens a control, so it needs the 6-digit code
on the dashboard or API (FR-052).

``BotController`` holds the logic and returns ``Reply`` values, so it is tested without Telegram.
The composition root supplies ``BotActions`` (the real services).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from aqta.core.errors import AqtaError
from aqta.core.logs import get_logger
from aqta.core.timeutil import format_ist
from aqta.proposals import Proposal, ProposalStatus

log = get_logger(__name__)

MAX_SIZE_CHOICES = 6
TELEGRAM_REASON = "rejected on Telegram"


class ProposalCb(CallbackData, prefix="p"):
    """Button payload. Kept short: Telegram allows 64 bytes of callback data."""

    action: str  # a=approve, ac=confirm approve, r=reject, m=smaller, ms=set size, b=back
    pid: str
    sets: int = 0


@dataclass(frozen=True, slots=True)
class ApprovalOutcome:
    proposal: Proposal
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KillOutcome:
    active: bool
    cancelled_orders: int


class BotActions(Protocol):
    @property
    def mode(self) -> str: ...

    async def pending(self) -> list[Proposal]: ...

    async def get(self, proposal_id: str) -> Proposal: ...

    async def approve(self, proposal_id: str) -> ApprovalOutcome: ...

    async def reject(self, proposal_id: str, reason: str) -> Proposal: ...

    async def modify(self, proposal_id: str, sets: int) -> Proposal: ...

    async def kill(self, reason: str) -> KillOutcome: ...

    async def status(self) -> str: ...


@dataclass(frozen=True, slots=True)
class Reply:
    text: str
    keyboard: InlineKeyboardMarkup | None = None


def _inr(value: Decimal | None) -> str:
    return "undefined" if value is None else f"Rs {value:,.0f}"


def format_proposal(p: Proposal, mode: str) -> str:
    lines = [f"[{mode.upper()}] PROPOSAL {p.underlying} - {p.horizon.value}"]
    for i, leg in enumerate(p.legs, start=1):
        price = f" @ {leg.limit_price}" if leg.limit_price is not None else " @ market"
        lines.append(
            f"{i}. {leg.side.value} {leg.lots} lot(s) {leg.instrument.symbol} "
            f"({leg.instrument.exchange.value}, qty {leg.quantity}){price}"
        )
    rom = "-" if p.return_on_margin is None else f"{p.return_on_margin * 100:.1f}%"
    lines.append(
        f"Max loss {_inr(p.max_loss_inr)} | Margin {_inr(p.margin_required_inr)} | RoM {rom}"
    )
    lines.append(f"Size: {p.sets} set(s) | Valid until {format_ist(p.valid_until, '%H:%M IST')}")
    lines.append(p.label)
    lines.append(f"id {p.id}")
    return "\n".join(lines)


def _btn(text: str, action: str, pid: str, sets: int = 0) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text, callback_data=ProposalCb(action=action, pid=pid, sets=sets).pack()
    )


def card_keyboard(p: Proposal) -> InlineKeyboardMarkup:
    row = [_btn("Approve", "a", p.id), _btn("Reject", "r", p.id)]
    if p.sets > 1:
        row.append(_btn("Smaller", "m", p.id))
    return InlineKeyboardMarkup(inline_keyboard=[row])


def proposal_card(p: Proposal, mode: str) -> Reply:
    open_ = p.status is ProposalStatus.PENDING_APPROVAL
    return Reply(format_proposal(p, mode), card_keyboard(p) if open_ else None)


class BotController:
    def __init__(self, actions: BotActions) -> None:
        self._actions = actions

    def help(self) -> Reply:
        return Reply(
            f"AQTA online. Mode: {self._actions.mode.upper()}.\n"
            "Proposals arrive here with Approve / Reject / Smaller buttons.\n"
            "/proposals - proposals waiting for you\n"
            "/status - mode and kill switch\n"
            "/kill <reason> - stop everything now\n"
            "/release - how to release the kill switch"
        )

    async def status(self) -> Reply:
        return Reply(await self._actions.status())

    async def proposals(self) -> list[Reply]:
        pending = await self._actions.pending()
        if not pending:
            return [Reply("No proposals waiting.")]
        return [proposal_card(p, self._actions.mode) for p in pending]

    async def kill(self, reason: str) -> Reply:
        reason = reason.strip() or "kill switch from Telegram"
        if len(reason) < 3:
            reason = f"Telegram: {reason}"
        outcome = await self._actions.kill(reason[:500])
        return Reply(
            "KILL SWITCH ACTIVE. New orders are blocked; "
            f"{outcome.cancelled_orders} open order(s) cancelled.\n"
            "Release it from the dashboard or API with your 6-digit code."
        )

    def release(self) -> Reply:
        return Reply(
            "Releasing the kill switch loosens a control, so it needs your 6-digit code. "
            "Use the dashboard or POST /api/v1/kill-switch with X-TOTP."
        )

    async def on_callback(self, cb: ProposalCb) -> Reply:
        """The reply edits the message that held the button."""
        mode = self._actions.mode
        try:
            if cb.action in ("a", "m", "b"):
                p = await self._actions.get(cb.pid)
                if p.status is not ProposalStatus.PENDING_APPROVAL:
                    return Reply(
                        format_proposal(p, mode) + f"\n\nThis proposal is {p.status.value}."
                    )
            if cb.action == "a":
                confirm = InlineKeyboardMarkup(
                    inline_keyboard=[[_btn("Confirm approve", "ac", p.id), _btn("Back", "b", p.id)]]
                )
                return Reply(format_proposal(p, mode) + "\n\nApprove this proposal?", confirm)
            if cb.action == "ac":
                outcome = await self._actions.approve(cb.pid)
                text = format_proposal(outcome.proposal, mode)
                return Reply("\n".join([text, "", "APPROVED", *outcome.lines]))
            if cb.action == "r":
                p = await self._actions.reject(cb.pid, TELEGRAM_REASON)
                return Reply(format_proposal(p, mode) + "\n\nREJECTED")
            if cb.action == "m":
                sizes = [_btn(f"{n} set(s)", "ms", p.id, n) for n in range(1, p.sets)][
                    :MAX_SIZE_CHOICES
                ]
                keyboard = InlineKeyboardMarkup(inline_keyboard=[sizes, [_btn("Back", "b", p.id)]])
                return Reply(format_proposal(p, mode) + "\n\nChoose a smaller size:", keyboard)
            if cb.action == "ms":
                smaller = await self._actions.modify(cb.pid, cb.sets)
                old = await self._actions.get(cb.pid)
                return Reply(
                    format_proposal(old, mode)
                    + f"\n\nREPLACED by {smaller.id} ({cb.sets} set(s)), sent as a new message."
                )
            if cb.action == "b":
                return proposal_card(p, mode)
        except AqtaError as exc:
            log.info(
                "telegram.action_refused", action=cb.action, proposal_id=cb.pid, error=str(exc)
            )
            return Reply(f"Could not do that: {exc}")
        return Reply("Unknown action.")
