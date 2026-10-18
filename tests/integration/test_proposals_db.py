"""SqlProposalRepository against a real Postgres (FR-011: proposals survive restarts)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from aqta.audit import InMemoryAuditLog
from aqta.core.clock import FrozenClock
from aqta.core.db import SessionFactory
from aqta.core.errors import InvalidTransitionError, NotFoundError
from aqta.proposals import (
    ApprovalService,
    ApprovalTokenService,
    InMemoryNonceStore,
    ProposalService,
    ProposalStatus,
)
from aqta.proposals.adapters import SqlProposalRepository
from aqta.proposals.models import ApprovalRow
from conftest import TEST_APPROVAL_SECRET
from factories import make_proposal

pytestmark = pytest.mark.integration


def _service(session_factory: SessionFactory, clock: FrozenClock) -> ProposalService:
    tokens = ApprovalTokenService(TEST_APPROVAL_SECRET, clock, InMemoryNonceStore())
    audit = InMemoryAuditLog(clock)
    repo = SqlProposalRepository(session_factory, clock)
    return ProposalService(repo, ApprovalService(tokens, audit, clock), tokens, audit, clock)


async def test_round_trip_and_lifecycle(
    session_factory: SessionFactory, clock: FrozenClock
) -> None:
    service = _service(session_factory, clock)
    p = await service.submit(make_proposal(clock, lots=(4, 2), rationale={"why": "test"}))
    with pytest.raises(InvalidTransitionError):
        await service.submit(p)

    # A fresh repository (as after a restart) sees the same proposal, legs and all.
    loaded = await _service(session_factory, clock).get(p.id)
    assert loaded == p

    smaller = await service.modify(p.id, "kashyap", 1)
    assert (await service.get(p.id)).status is ProposalStatus.CANCELLED
    await service.approve(smaller.id, "kashyap", "api")
    assert (await service.get(smaller.id)).status is ProposalStatus.APPROVED
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(ApprovalRow)
            .where(ApprovalRow.proposal_id == smaller.id)
        )
    assert count == 2

    clock.advance(seconds=1)
    later = await service.submit(
        make_proposal(clock, valid_until=clock.now() + timedelta(minutes=1))
    )
    found = await service.find()
    assert [x.id for x in found][:1] == [later.id]
    assert {x.id for x in await service.find([ProposalStatus.APPROVED])} == {smaller.id}


async def test_save_unknown_raises(session_factory: SessionFactory, clock: FrozenClock) -> None:
    with pytest.raises(NotFoundError):
        await SqlProposalRepository(session_factory, clock).save(make_proposal(clock))
