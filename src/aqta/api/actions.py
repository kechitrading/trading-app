"""Actions shared by the HTTP API and the Telegram bot (composition root).

Both channels approve through ``approve_and_execute`` so paper fills, hedge-first ordering and the
live-mode rule (CR-003: no orders sent) behave the same everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

from aqta.api.container import Container
from aqta.core.timeutil import format_ist
from aqta.execution import OrderResult, execute_paper
from aqta.notifications import ApprovalOutcome, KillOutcome
from aqta.proposals import Proposal, ProposalStatus

LIVE_NOTE = "Approved. Place the orders in the Angel One app (manual execution, CR-003)."
FILLED_NOTE = "Paper orders filled."
BLOCKED_NOTE = "Stopped at a blocked leg; see reasons."


@dataclass(frozen=True, slots=True)
class ApproveResult:
    proposal: Proposal
    mode: str
    orders: list[OrderResult]
    note: str


async def approve_and_execute(
    container: Container, proposal_id: str, actor: str, channel: str
) -> ApproveResult:
    """FR-023, FR-024. Paper mode fills each leg through the gateway, risk-reducing legs first
    (FR-025, FR-030). Live mode sends nothing; the order ticket comes from FR-077."""
    proposal, tokens = await container.proposals.approve(proposal_id, actor, channel)
    if not container.settings.is_paper:
        return ApproveResult(proposal, "live", [], LIVE_NOTE)
    results = await execute_paper(container.gateway, proposal.legs, tokens)
    all_done = len(results) == len(proposal.legs) and all(r.accepted for r in results)
    if all_done:
        proposal = await container.proposals.mark_executed(proposal_id, actor)
    return ApproveResult(proposal, "paper", results, FILLED_NOTE if all_done else BLOCKED_NOTE)


async def trigger_kill_switch(container: Container, actor: str, reason: str) -> KillOutcome:
    """FR-034: block new orders and cancel open ones."""
    open_before = len(container.gateway.open_orders())
    state = await container.kill_switch.trigger(actor, reason)
    return KillOutcome(state.active, open_before - len(container.gateway.open_orders()))


class ContainerBotActions:
    """``BotActions`` for the Telegram bot, backed by the API container. Channel: telegram."""

    actor = "kashyap"  # single user; the allowlist middleware already checked the account

    def __init__(self, container: Container) -> None:
        self._c = container

    @property
    def mode(self) -> str:
        return self._c.settings.trading_mode.value

    async def pending(self) -> list[Proposal]:
        return await self._c.proposals.find([ProposalStatus.PENDING_APPROVAL])

    async def get(self, proposal_id: str) -> Proposal:
        await self._c.proposals.expire_due()
        return await self._c.proposals.get(proposal_id)

    async def approve(self, proposal_id: str) -> ApprovalOutcome:
        result = await approve_and_execute(self._c, proposal_id, self.actor, "telegram")
        lines = [result.note]
        for r in result.orders:
            state = r.state.value if r.state is not None else "blocked"
            detail = "" if r.accepted else f" ({'; '.join(r.reasons)})"
            lines.append(f"{r.client_order_id}: {state}{detail}")
        return ApprovalOutcome(result.proposal, tuple(lines))

    async def reject(self, proposal_id: str, reason: str) -> Proposal:
        return await self._c.proposals.reject(proposal_id, self.actor, reason)

    async def modify(self, proposal_id: str, sets: int) -> Proposal:
        return await self._c.proposals.modify(proposal_id, self.actor, sets)

    async def kill(self, reason: str) -> KillOutcome:
        return await trigger_kill_switch(self._c, self.actor, reason)

    async def status(self) -> str:
        state = await self._c.kill_switch.state()
        if state is not None and state.active:
            ks = f"ACTIVE since {format_ist(state.updated_at)} ({state.reason})"
        else:
            ks = "off"
        pending = len(await self.pending())
        return (
            f"Mode: {self.mode.upper()}\nKill switch: {ks}\n"
            f"Open orders: {len(self._c.gateway.open_orders())}\nProposals waiting: {pending}"
        )
