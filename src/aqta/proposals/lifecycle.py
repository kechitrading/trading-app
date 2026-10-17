"""Trade proposal schema and lifecycle with validity window (FR-011, FR-012, FR-023)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aqta.audit import AuditSink
from aqta.core.clock import Clock
from aqta.core.errors import InvalidTransitionError
from aqta.core.trading import OrderRequest
from aqta.proposals.tokens import ApprovalTokenService


class Horizon(StrEnum):
    INTRADAY = "intraday"
    SWING = "swing"
    POSITIONAL = "positional"


class ProposalStatus(StrEnum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    EXECUTED = "executed"
    CANCELLED = "cancelled"


_ALLOWED: dict[ProposalStatus, frozenset[ProposalStatus]] = {
    ProposalStatus.DRAFT: frozenset({ProposalStatus.PENDING_APPROVAL, ProposalStatus.CANCELLED}),
    ProposalStatus.PENDING_APPROVAL: frozenset(
        {
            ProposalStatus.APPROVED,
            ProposalStatus.REJECTED,
            ProposalStatus.EXPIRED,
            ProposalStatus.CANCELLED,
        }
    ),
    ProposalStatus.APPROVED: frozenset({ProposalStatus.EXECUTED, ProposalStatus.CANCELLED}),
    ProposalStatus.REJECTED: frozenset(),
    ProposalStatus.EXPIRED: frozenset(),
    ProposalStatus.EXECUTED: frozenset(),
    ProposalStatus.CANCELLED: frozenset(),
}


class Proposal(BaseModel):
    """A trade idea awaiting Kashyap's decision. Legs are the exact orders to be approved."""

    model_config = ConfigDict(frozen=True)

    id: str
    created_at: datetime
    valid_until: datetime
    horizon: Horizon
    underlying: str
    strategy_id: str | None = None
    legs: tuple[OrderRequest, ...] = Field(min_length=1)
    max_loss_inr: Decimal | None = None
    margin_required_inr: Decimal | None = None
    return_on_margin: Decimal | None = None
    status: ProposalStatus = ProposalStatus.DRAFT
    # TODO(FR-010, FR-043): top contributing signals, evidence links, rationale pack reference.
    rationale: dict[str, Any] = Field(default_factory=dict)
    label: str = "Proposal only - not an order (FR-016)"


def transition(proposal: Proposal, to: ProposalStatus) -> Proposal:
    if to not in _ALLOWED[proposal.status]:
        raise InvalidTransitionError(
            f"proposal {proposal.id}: {proposal.status} -> {to} not allowed"
        )
    return proposal.model_copy(update={"status": to})


class ApprovalService:
    """Turns Kashyap's approve action into one signed token per leg (FR-023, FR-024)."""

    def __init__(self, tokens: ApprovalTokenService, audit: AuditSink, clock: Clock) -> None:
        self._tokens = tokens
        self._audit = audit
        self._clock = clock

    async def approve(
        self, proposal: Proposal, actor: str, channel: str
    ) -> tuple[Proposal, dict[str, str]]:
        now = self._clock.now()
        if now >= proposal.valid_until:
            expired = transition(proposal, ProposalStatus.EXPIRED)
            await self._audit.record("proposal.expired", {"proposal_id": proposal.id}, actor)
            raise InvalidTransitionError(f"proposal {expired.id} expired at {proposal.valid_until}")
        approved = transition(proposal, ProposalStatus.APPROVED)
        ttl = max(1, int((proposal.valid_until - now).total_seconds()))
        tokens = {leg.client_order_id: self._tokens.issue(leg, actor, ttl) for leg in proposal.legs}
        await self._audit.record(
            "proposal.approved",
            {
                "proposal_id": proposal.id,
                "channel": channel,
                "legs": [leg.client_order_id for leg in proposal.legs],
                "order_hashes": [leg.payload_hash() for leg in proposal.legs],
            },
            actor,
        )
        return approved, tokens

    async def reject(self, proposal: Proposal, actor: str, reason: str) -> Proposal:
        rejected = transition(proposal, ProposalStatus.REJECTED)
        await self._audit.record(
            "proposal.rejected", {"proposal_id": proposal.id, "reason": reason}, actor
        )
        return rejected
