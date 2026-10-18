"""Versioned API. Every route needs the API token; routes that approve orders or loosen controls
also need a fresh TOTP code in ``X-TOTP`` (FR-052, NFR-009)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from aqta.api.deps import Actor, ContainerDep, TotpHeader, check_mfa
from aqta.core.timeutil import format_ist

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


class ProposalOut(BaseModel):
    id: str
    status: str
    underlying: str
    horizon: str
    valid_until: datetime
    label: str


@router.get("/proposals")
async def list_proposals(container: ContainerDep, actor: Actor) -> list[ProposalOut]:
    """Stub list. TODO(FR-011, FR-023): proposal repository, approve/reject/modify endpoints."""
    return [
        ProposalOut(
            id=p.id,
            status=p.status.value,
            underlying=p.underlying,
            horizon=p.horizon.value,
            valid_until=p.valid_until,
            label=p.label,
        )
        for p in container.proposals
    ]
