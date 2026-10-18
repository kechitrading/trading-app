from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from aqta.audit import InMemoryAuditLog
from aqta.core.clock import FrozenClock
from aqta.core.errors import InvalidTransitionError, NotFoundError
from aqta.core.settings import ProposalSettings
from aqta.proposals import (
    ApprovalService,
    ApprovalTokenService,
    Horizon,
    InMemoryNonceStore,
    InMemoryProposalRepository,
    ProposalService,
    ProposalStatus,
    resized,
    validity_seconds,
)
from conftest import TEST_APPROVAL_SECRET
from factories import make_proposal


@pytest.fixture
def repo() -> InMemoryProposalRepository:
    return InMemoryProposalRepository()


@pytest.fixture
def audit(clock: FrozenClock) -> InMemoryAuditLog:
    return InMemoryAuditLog(clock)


@pytest.fixture
def tokens(clock: FrozenClock) -> ApprovalTokenService:
    return ApprovalTokenService(TEST_APPROVAL_SECRET, clock, InMemoryNonceStore())


@pytest.fixture
def service(
    repo: InMemoryProposalRepository,
    tokens: ApprovalTokenService,
    audit: InMemoryAuditLog,
    clock: FrozenClock,
) -> ProposalService:
    return ProposalService(repo, ApprovalService(tokens, audit, clock), tokens, audit, clock)


def kinds(audit: InMemoryAuditLog) -> list[str]:
    return [e.event_type for e in audit.entries]


def test_validity_by_horizon() -> None:
    s = ProposalSettings()
    assert validity_seconds(Horizon.INTRADAY, s) == 300
    assert validity_seconds(Horizon.SWING, s) == 1800
    assert validity_seconds(Horizon.POSITIONAL, s) == 3600


def test_sets_is_gcd_of_leg_lots(clock: FrozenClock) -> None:
    assert make_proposal(clock, lots=(4, 2)).sets == 2
    assert make_proposal(clock, lots=(3, 2)).sets == 1
    assert make_proposal(clock, lots=(6,)).sets == 6


async def test_submit_and_find(service: ProposalService, clock: FrozenClock) -> None:
    draft = make_proposal(clock, status=ProposalStatus.DRAFT)
    stored = await service.submit(draft)
    assert stored.status is ProposalStatus.PENDING_APPROVAL
    clock.advance(seconds=1)
    newer = await service.submit(make_proposal(clock))
    assert [p.id for p in await service.find()] == [newer.id, stored.id]
    assert await service.find([ProposalStatus.REJECTED]) == []
    with pytest.raises(InvalidTransitionError, match="already exists"):
        await service.submit(newer)


async def test_get_unknown_raises(service: ProposalService) -> None:
    with pytest.raises(NotFoundError):
        await service.get("nope")


async def test_approve_issues_one_bound_token_per_leg(
    service: ProposalService,
    repo: InMemoryProposalRepository,
    tokens: ApprovalTokenService,
    audit: InMemoryAuditLog,
    clock: FrozenClock,
) -> None:
    p = await service.submit(make_proposal(clock, lots=(2, 2)))
    approved, issued = await service.approve(p.id, "kashyap", "api")
    assert approved.status is ProposalStatus.APPROVED
    assert (await service.get(p.id)).status is ProposalStatus.APPROVED
    assert set(issued) == {leg.client_order_id for leg in p.legs}
    for leg in p.legs:
        assert tokens.verify(issued[leg.client_order_id], leg).actor == "kashyap"
    assert len(repo.approvals) == 2
    assert {r.channel for r in repo.approvals} == {"api"}
    assert repo.approvals[0].expires_at == p.valid_until
    assert "proposal.approved" in kinds(audit)


async def test_approve_twice_refused(service: ProposalService, clock: FrozenClock) -> None:
    p = await service.submit(make_proposal(clock))
    await service.approve(p.id, "kashyap", "api")
    with pytest.raises(InvalidTransitionError, match="approved"):
        await service.approve(p.id, "kashyap", "api")


async def test_approve_after_window_expires_it(
    service: ProposalService, audit: InMemoryAuditLog, clock: FrozenClock
) -> None:
    p = await service.submit(make_proposal(clock))
    clock.advance(minutes=5)
    with pytest.raises(InvalidTransitionError, match="expired"):
        await service.approve(p.id, "kashyap", "api")
    assert (await service.get(p.id)).status is ProposalStatus.EXPIRED
    assert "proposal.expired" in kinds(audit)


async def test_find_expires_overdue_proposals(service: ProposalService, clock: FrozenClock) -> None:
    soon = await service.submit(make_proposal(clock))
    later = await service.submit(
        make_proposal(clock, valid_until=clock.now() + timedelta(minutes=30))
    )
    clock.advance(minutes=6)
    statuses = {p.id: p.status for p in await service.find()}
    assert statuses == {soon.id: ProposalStatus.EXPIRED, later.id: ProposalStatus.PENDING_APPROVAL}


async def test_reject(
    service: ProposalService, audit: InMemoryAuditLog, clock: FrozenClock
) -> None:
    p = await service.submit(make_proposal(clock))
    rejected = await service.reject(p.id, "kashyap", "too close to results")
    assert rejected.status is ProposalStatus.REJECTED
    assert (await service.get(p.id)).status is ProposalStatus.REJECTED
    assert "proposal.rejected" in kinds(audit)
    with pytest.raises(InvalidTransitionError):
        await service.approve(p.id, "kashyap", "api")


async def test_modify_reduces_all_legs_by_the_same_ratio(
    service: ProposalService, audit: InMemoryAuditLog, clock: FrozenClock
) -> None:
    p = await service.submit(make_proposal(clock, lots=(4, 2)))
    assert p.sets == 2
    smaller = await service.modify(p.id, "kashyap", 1)
    assert smaller.id != p.id and smaller.status is ProposalStatus.PENDING_APPROVAL
    assert [leg.lots for leg in smaller.legs] == [2, 1]
    assert all(leg.proposal_id == smaller.id for leg in smaller.legs)
    assert {leg.client_order_id for leg in smaller.legs}.isdisjoint(
        leg.client_order_id for leg in p.legs
    )
    assert smaller.max_loss_inr == Decimal("3000.00")
    assert smaller.margin_required_inr == Decimal("60000.00")
    assert smaller.legs[0].max_loss_inr == Decimal("2000.00")
    assert smaller.return_on_margin == p.return_on_margin
    assert smaller.valid_until == p.valid_until
    assert smaller.rationale["modified_from"] == p.id

    original = await service.get(p.id)
    assert original.status is ProposalStatus.CANCELLED
    assert original.rationale["superseded_by"] == smaller.id
    assert "proposal.modified" in kinds(audit)
    approved, _ = await service.approve(smaller.id, "kashyap", "api")
    assert approved.status is ProposalStatus.APPROVED


@pytest.mark.parametrize("new_sets", [0, 2, 3])
async def test_modify_cannot_keep_or_increase_size(
    service: ProposalService, clock: FrozenClock, new_sets: int
) -> None:
    p = await service.submit(make_proposal(clock, lots=(4, 2)))
    with pytest.raises(InvalidTransitionError, match="only be reduced"):
        await service.modify(p.id, "kashyap", new_sets)
    assert (await service.get(p.id)).status is ProposalStatus.PENDING_APPROVAL


async def test_single_set_cannot_be_modified(service: ProposalService, clock: FrozenClock) -> None:
    p = await service.submit(make_proposal(clock, lots=(3, 2)))
    with pytest.raises(InvalidTransitionError):
        await service.modify(p.id, "kashyap", 1)


def test_resized_keeps_undefined_loss_undefined(clock: FrozenClock) -> None:
    p = make_proposal(clock, lots=(2,), max_loss_inr=None, margin_required_inr=None)
    smaller = resized(p, 1, "prop_x", clock.now())
    assert smaller.max_loss_inr is None and smaller.margin_required_inr is None


async def test_mark_executed(service: ProposalService, clock: FrozenClock) -> None:
    p = await service.submit(make_proposal(clock))
    with pytest.raises(InvalidTransitionError):
        await service.mark_executed(p.id)
    await service.approve(p.id, "kashyap", "api")
    assert (await service.mark_executed(p.id)).status is ProposalStatus.EXECUTED


async def test_repo_save_unknown_raises(
    repo: InMemoryProposalRepository, clock: FrozenClock
) -> None:
    with pytest.raises(NotFoundError):
        await repo.save(make_proposal(clock))
