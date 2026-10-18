"""Versioned API. Every route needs the API token; routes that approve orders or loosen controls
also need a fresh TOTP code in ``X-TOTP`` (FR-052, NFR-009)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from aqta.api.actions import approve_and_execute
from aqta.api.deps import Actor, ContainerDep, MfaActor, TotpHeader, check_mfa
from aqta.core.timeutil import format_ist
from aqta.proposals import Proposal, ProposalStatus

router = APIRouter(prefix="/api/v1", tags=["v1"])


class ModeOut(BaseModel):
    trading_mode: str
    live_trading_enabled: bool
    algo_tag: str


@router.get("/mode")
async def get_mode(container: ContainerDep, actor: Actor) -> ModeOut:
    s = container.settings
    return ModeOut(
        trading_mode=s.trading_mode.value,
        live_trading_enabled=s.live_trading_enabled,
        algo_tag=s.algo_tag,
    )


class KillSwitchOut(BaseModel):
    active: bool
    updated_at: datetime | None = None
    updated_at_ist: str | None = None
    actor: str | None = None
    reason: str | None = None
    cancelled_orders: int | None = None


class KillSwitchIn(BaseModel):
    action: Literal["trigger", "release"] = "trigger"
    reason: str = Field(min_length=3, max_length=500)


@router.get("/kill-switch")
async def get_kill_switch(container: ContainerDep, actor: Actor) -> KillSwitchOut:
    state = await container.kill_switch.state()
    if state is None:
        return KillSwitchOut(active=False)
    return KillSwitchOut(
        active=state.active,
        updated_at=state.updated_at,
        updated_at_ist=format_ist(state.updated_at),
        actor=state.actor,
        reason=state.reason,
    )


@router.post("/kill-switch")
async def post_kill_switch(
    body: KillSwitchIn, container: ContainerDep, actor: Actor, totp: TotpHeader = None
) -> KillSwitchOut:
    """FR-034: trigger cancels all open orders and blocks new ones. Release needs a reason.

    Triggering needs only the API token, so the switch stays available in an emergency.
    Releasing loosens a control, so it also needs a TOTP code (FR-052).
    """
    if body.action == "release":
        check_mfa(container, totp)
    open_before = len(container.gateway.open_orders())
    if body.action == "trigger":
        state = await container.kill_switch.trigger(actor, body.reason)
    else:
        state = await container.kill_switch.release(actor, body.reason)
    return KillSwitchOut(
        active=state.active,
        updated_at=state.updated_at,
        updated_at_ist=format_ist(state.updated_at),
        actor=state.actor,
        reason=state.reason,
        cancelled_orders=open_before - len(container.gateway.open_orders()),
    )


class LegOut(BaseModel):
    client_order_id: str
    symbol: str
    exchange: str
    side: str
    quantity: int
    lots: int
    order_type: str
    limit_price: Decimal | None
    risk_effect: str


class ProposalOut(BaseModel):
    id: str
    status: str
    underlying: str
    horizon: str
    created_at: datetime
    valid_until: datetime
    valid_until_ist: str
    sets: int
    max_loss_inr: Decimal | None
    margin_required_inr: Decimal | None
    return_on_margin: Decimal | None
    legs: list[LegOut]
    rationale: dict[str, Any]
    label: str

    @classmethod
    def of(cls, p: Proposal) -> ProposalOut:
        return cls(
            id=p.id,
            status=p.status.value,
            underlying=p.underlying,
            horizon=p.horizon.value,
            created_at=p.created_at,
            valid_until=p.valid_until,
            valid_until_ist=format_ist(p.valid_until),
            sets=p.sets,
            max_loss_inr=p.max_loss_inr,
            margin_required_inr=p.margin_required_inr,
            return_on_margin=p.return_on_margin,
            legs=[
                LegOut(
                    client_order_id=leg.client_order_id,
                    symbol=leg.instrument.symbol,
                    exchange=leg.instrument.exchange.value,
                    side=leg.side.value,
                    quantity=leg.quantity,
                    lots=leg.lots,
                    order_type=leg.order_type.value,
                    limit_price=leg.limit_price,
                    risk_effect=leg.risk_effect.value,
                )
                for leg in p.legs
            ],
            rationale=p.rationale,
            label=p.label,
        )


@router.get("/proposals")
async def list_proposals(
    container: ContainerDep, actor: Actor, status: ProposalStatus | None = None
) -> list[ProposalOut]:
    """FR-011, FR-023: newest first. Overdue pending proposals are marked expired first."""
    statuses = None if status is None else [status]
    return [ProposalOut.of(p) for p in await container.proposals.find(statuses)]


@router.get("/proposals/{proposal_id}")
async def get_proposal(proposal_id: str, container: ContainerDep, actor: Actor) -> ProposalOut:
    await container.proposals.expire_due()
    return ProposalOut.of(await container.proposals.get(proposal_id))


class LegResultOut(BaseModel):
    client_order_id: str
    accepted: bool
    stage: str | None
    reasons: list[str]
    state: str | None


class ApproveOut(BaseModel):
    proposal: ProposalOut
    mode: str
    orders: list[LegResultOut]
    note: str


@router.post("/proposals/{proposal_id}/approve")
async def approve_proposal(
    proposal_id: str, container: ContainerDep, actor: MfaActor
) -> ApproveOut:
    """FR-023, FR-024, FR-052 (needs X-TOTP). Paper mode fills each leg on the paper broker
    through the order gateway, risk-reducing legs first (FR-025, FR-030). Live mode sends nothing
    (CR-003): the proposal is approved and the order ticket comes from FR-077."""
    result = await approve_and_execute(container, proposal_id, actor, "api")
    return ApproveOut(
        proposal=ProposalOut.of(result.proposal),
        mode=result.mode,
        orders=[
            LegResultOut(
                client_order_id=r.client_order_id,
                accepted=r.accepted,
                stage=None if r.stage is None else r.stage.value,
                reasons=list(r.reasons),
                state=None if r.state is None else r.state.value,
            )
            for r in result.orders
        ],
        note=result.note,
    )


class RejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(
    proposal_id: str, body: RejectIn, container: ContainerDep, actor: Actor
) -> ProposalOut:
    """FR-023. Rejecting adds no risk, so the API token is enough."""
    return ProposalOut.of(await container.proposals.reject(proposal_id, actor, body.reason))


class ModifyIn(BaseModel):
    sets: int = Field(ge=1, description="New size in sets; must be lower than the current sets.")


@router.post("/proposals/{proposal_id}/modify")
async def modify_proposal(
    proposal_id: str, body: ModifyIn, container: ContainerDep, actor: Actor
) -> ProposalOut:
    """FR-023, reduce size only: the original is cancelled and a smaller copy opens for
    approval. Smaller size cannot add risk, so the API token is enough; approving the copy
    needs TOTP."""
    return ProposalOut.of(await container.proposals.modify(proposal_id, actor, body.sets))
