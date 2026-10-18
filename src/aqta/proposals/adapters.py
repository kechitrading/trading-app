"""Proposal infrastructure: Redis nonce store (single-use tokens) and the SQL proposal store."""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from aqta.core.clock import Clock
from aqta.core.db import SessionFactory, session_scope
from aqta.core.errors import InvalidTransitionError, NotFoundError
from aqta.core.hashing import to_jsonable
from aqta.core.ids import new_id
from aqta.core.trading import OrderRequest
from aqta.proposals.lifecycle import Horizon, Proposal, ProposalStatus
from aqta.proposals.models import ApprovalRow, ProposalRow
from aqta.proposals.service import ApprovalRecord

NONCE_PREFIX = "aqta:approval:nonce:"


def _to_row(proposal: Proposal, now: datetime) -> dict[str, Any]:
    return {
        "id": proposal.id,
        "created_at": proposal.created_at,
        "updated_at": now,
        "status": proposal.status.value,
        "horizon": proposal.horizon.value,
        "strategy_id": proposal.strategy_id,
        "underlying": proposal.underlying,
        "legs": [leg.model_dump(mode="json") for leg in proposal.legs],
        "max_loss_inr": proposal.max_loss_inr,
        "margin_required_inr": proposal.margin_required_inr,
        "return_on_margin": proposal.return_on_margin,
        "valid_until": proposal.valid_until,
        "rationale": to_jsonable(proposal.rationale),
    }


def _from_row(row: ProposalRow) -> Proposal:
    return Proposal(
        id=row.id,
        created_at=row.created_at,
        valid_until=row.valid_until,
        horizon=Horizon(row.horizon),
        underlying=row.underlying,
        strategy_id=row.strategy_id,
        legs=tuple(OrderRequest.model_validate(leg) for leg in row.legs),
        max_loss_inr=row.max_loss_inr,
        margin_required_inr=row.margin_required_inr,
        return_on_margin=row.return_on_margin,
        status=ProposalStatus(row.status),
        rationale=row.rationale or {},
    )


class SqlProposalRepository:
    """FR-011: proposals survive restarts. Approvals are append-only rows per approved leg."""

    def __init__(self, session_factory: SessionFactory, clock: Clock) -> None:
        self._sessions = session_factory
        self._clock = clock

    async def add(self, proposal: Proposal) -> None:
        async with session_scope(self._sessions) as session:
            if await session.get(ProposalRow, proposal.id) is not None:
                raise InvalidTransitionError(f"proposal {proposal.id} already exists")
            session.add(ProposalRow(**_to_row(proposal, self._clock.now())))

    async def save(self, proposal: Proposal) -> None:
        async with session_scope(self._sessions) as session:
            row = await session.get(ProposalRow, proposal.id)
            if row is None:
                raise NotFoundError(f"proposal {proposal.id} not found")
            for key, value in _to_row(proposal, self._clock.now()).items():
                if key not in ("id", "created_at"):
                    setattr(row, key, value)

    async def get(self, proposal_id: str) -> Proposal | None:
        async with self._sessions() as session:
            row = await session.get(ProposalRow, proposal_id)
            return None if row is None else _from_row(row)

    async def find(
        self, statuses: Iterable[ProposalStatus] | None = None, limit: int = 50
    ) -> list[Proposal]:
        stmt = select(ProposalRow).order_by(ProposalRow.created_at.desc()).limit(limit)
        if statuses is not None:
            stmt = stmt.where(ProposalRow.status.in_([s.value for s in statuses]))
        async with self._sessions() as session:
            return [_from_row(row) for row in await session.scalars(stmt)]

    async def record_approvals(self, records: list[ApprovalRecord]) -> None:
        async with session_scope(self._sessions) as session:
            for r in records:
                session.add(
                    ApprovalRow(
                        id=new_id("appr"),
                        proposal_id=r.proposal_id,
                        decision="approved",
                        actor=r.actor,
                        channel=r.channel,
                        order_payload_hash=r.order_payload_hash,
                        token_nonce=r.token_nonce,
                        issued_at=r.issued_at,
                        expires_at=r.expires_at,
                    )
                )


class RedisNonceStore:
    def __init__(self, redis: Any) -> None:
        self._redis = redis

    async def consume(self, nonce: str, expires_at: datetime) -> bool:
        ttl = max(1, math.ceil((expires_at - datetime.now(UTC)).total_seconds()) + 60)
        return bool(await self._redis.set(f"{NONCE_PREFIX}{nonce}", "1", nx=True, ex=ttl))
