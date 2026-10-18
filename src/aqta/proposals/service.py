"""Proposal store and the approve / reject / modify actions (FR-011, FR-023, FR-024).

``ProposalService`` is what the API and (later) the Telegram bot call. It never sends orders:
after approval, the caller hands the per-leg tokens to ``OrderGateway`` in paper mode, or shows an
order ticket in live manual mode (CR-003, RULE-016).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from aqta.audit import AuditSink
from aqta.core.clock import Clock
from aqta.core.errors import InvalidTransitionError, NotFoundError
from aqta.core.ids import new_id
from aqta.proposals.lifecycle import (
    ApprovalService,
    Proposal,
    ProposalStatus,
    resized,
    transition,
)
from aqta.proposals.tokens import ApprovalTokenService


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    """One approved leg, as stored in the ``approvals`` table."""

    proposal_id: str
    client_order_id: str
    actor: str
    channel: str
    order_payload_hash: str
    token_nonce: str
    issued_at: datetime
    expires_at: datetime


class ProposalRepository(Protocol):
    async def add(self, proposal: Proposal) -> None: ...

    async def save(self, proposal: Proposal) -> None: ...

    async def get(self, proposal_id: str) -> Proposal | None: ...

    async def find(
        self, statuses: Iterable[ProposalStatus] | None = None, limit: int = 50
    ) -> list[Proposal]: ...

    async def record_approvals(self, records: list[ApprovalRecord]) -> None: ...


class InMemoryProposalRepository:
    def __init__(self) -> None:
        self._items: dict[str, Proposal] = {}
        self.approvals: list[ApprovalRecord] = []

    async def add(self, proposal: Proposal) -> None:
        if proposal.id in self._items:
            raise InvalidTransitionError(f"proposal {proposal.id} already exists")
        self._items[proposal.id] = proposal

    async def save(self, proposal: Proposal) -> None:
        if proposal.id not in self._items:
            raise NotFoundError(f"proposal {proposal.id} not found")
        self._items[proposal.id] = proposal

    async def get(self, proposal_id: str) -> Proposal | None:
        return self._items.get(proposal_id)

    async def find(
        self, statuses: Iterable[ProposalStatus] | None = None, limit: int = 50
    ) -> list[Proposal]:
        wanted = set(statuses) if statuses is not None else None
        items = [p for p in self._items.values() if wanted is None or p.status in wanted]
        return sorted(items, key=lambda p: p.created_at, reverse=True)[:limit]

    async def record_approvals(self, records: list[ApprovalRecord]) -> None:
        self.approvals.extend(records)


class ProposalService:
    def __init__(
        self,
        repo: ProposalRepository,
        approvals: ApprovalService,
        tokens: ApprovalTokenService,
        audit: AuditSink,
        clock: Clock,
    ) -> None:
        self._repo = repo
        self._approvals = approvals
        self._tokens = tokens
        self._audit = audit
        self._clock = clock

    async def submit(self, proposal: Proposal, actor: str = "system") -> Proposal:
        """Store a new proposal and open it for approval."""
        pending = (
            proposal
            if proposal.status is ProposalStatus.PENDING_APPROVAL
            else transition(proposal, ProposalStatus.PENDING_APPROVAL)
        )
        await self._repo.add(pending)
        await self._audit.record(
            "proposal.submitted",
            {"proposal_id": pending.id, "valid_until": pending.valid_until.isoformat()},
            actor,
        )
        return pending

    async def get(self, proposal_id: str) -> Proposal:
        proposal = await self._repo.get(proposal_id)
        if proposal is None:
            raise NotFoundError(f"proposal {proposal_id} not found")
        return proposal

    async def find(
        self, statuses: Iterable[ProposalStatus] | None = None, limit: int = 50
    ) -> list[Proposal]:
        await self.expire_due()
        return await self._repo.find(statuses, limit)

    async def expire_due(self) -> list[Proposal]:
        """Mark pending proposals past their window as expired (FR-023)."""
        now = self._clock.now()
        expired = []
        for proposal in await self._repo.find([ProposalStatus.PENDING_APPROVAL], limit=1000):
            if now >= proposal.valid_until:
                expired.append(await self._expire(proposal))
        return expired

    async def approve(
        self, proposal_id: str, actor: str, channel: str
    ) -> tuple[Proposal, dict[str, str]]:
        """FR-023, FR-024: one single-use token per leg, bound to that leg's exact payload."""
        proposal = await self._open(proposal_id)
        approved, tokens = await self._approvals.approve(proposal, actor, channel)
        await self._repo.save(approved)
        records = []
        for leg in approved.legs:
            claims = self._tokens.verify(tokens[leg.client_order_id], leg)
            records.append(
                ApprovalRecord(
                    proposal_id=approved.id,
                    client_order_id=leg.client_order_id,
                    actor=actor,
                    channel=channel,
                    order_payload_hash=claims.order_hash,
                    token_nonce=claims.nonce,
                    issued_at=claims.issued_at,
                    expires_at=claims.expires_at,
                )
            )
        await self._repo.record_approvals(records)
        return approved, tokens

    async def reject(self, proposal_id: str, actor: str, reason: str) -> Proposal:
        proposal = await self._open(proposal_id)
        rejected = await self._approvals.reject(proposal, actor, reason)
        await self._repo.save(rejected)
        return rejected

    async def modify(self, proposal_id: str, actor: str, new_sets: int) -> Proposal:
        """Reduce size only (decided 2026-10-18). The original is cancelled and a smaller copy
        opens for approval; it still needs its own approval."""
        proposal = await self._open(proposal_id)
        smaller = resized(proposal, new_sets, new_id("prop"), self._clock.now())
        superseded = transition(proposal, ProposalStatus.CANCELLED).model_copy(
            update={"rationale": {**proposal.rationale, "superseded_by": smaller.id}}
        )
        await self._repo.save(superseded)
        await self._repo.add(smaller)
        await self._audit.record(
            "proposal.modified",
            {
                "proposal_id": proposal.id,
                "new_proposal_id": smaller.id,
                "sets": proposal.sets,
                "new_sets": new_sets,
            },
            actor,
        )
        return smaller

    async def mark_executed(self, proposal_id: str, actor: str = "system") -> Proposal:
        executed = transition(await self.get(proposal_id), ProposalStatus.EXECUTED)
        await self._repo.save(executed)
        await self._audit.record("proposal.executed", {"proposal_id": proposal_id}, actor)
        return executed

    async def _open(self, proposal_id: str) -> Proposal:
        """The proposal if it is still awaiting a decision; expires it first if overdue."""
        proposal = await self.get(proposal_id)
        if proposal.status is not ProposalStatus.PENDING_APPROVAL:
            raise InvalidTransitionError(f"proposal {proposal_id} is {proposal.status.value}")
        if self._clock.now() >= proposal.valid_until:
            await self._expire(proposal)
            raise InvalidTransitionError(
                f"proposal {proposal_id} expired at {proposal.valid_until.isoformat()}"
            )
        return proposal

    async def _expire(self, proposal: Proposal) -> Proposal:
        expired = transition(proposal, ProposalStatus.EXPIRED)
        await self._repo.save(expired)
        await self._audit.record("proposal.expired", {"proposal_id": proposal.id}, "system")
        return expired
