from __future__ import annotations

import base64
import json
from datetime import timedelta
from decimal import Decimal

import fakeredis
import pytest
from factories import make_order

from aqta.audit import InMemoryAuditLog
from aqta.core.clock import FrozenClock
from aqta.core.errors import ConfigError, InvalidTransitionError
from aqta.proposals import (
    ApprovalService,
    ApprovalTokenError,
    ApprovalTokenService,
    Horizon,
    InMemoryNonceStore,
    Proposal,
    ProposalStatus,
    TokenFailure,
    transition,
)
from aqta.proposals.adapters import RedisNonceStore

SECRET = "unit-test-secret-0123456789abcdef"


@pytest.fixture
def svc(clock: FrozenClock) -> ApprovalTokenService:
    return ApprovalTokenService(SECRET, clock, InMemoryNonceStore(), default_ttl_seconds=300)


def _fail(exc: pytest.ExceptionInfo[ApprovalTokenError]) -> TokenFailure:
    return exc.value.failure


async def test_valid_token_round_trip(svc: ApprovalTokenService) -> None:
    order = make_order()
    token = svc.issue(order, actor="kashyap")
    claims = await svc.verify_and_consume(token, order)
    assert claims.actor == "kashyap"
    assert claims.order_hash == order.payload_hash()
    assert claims.expires_at - claims.issued_at == timedelta(minutes=5)


@pytest.mark.parametrize("token", [None, ""])
async def test_missing_token(svc: ApprovalTokenService, token: str | None) -> None:
    with pytest.raises(ApprovalTokenError) as exc:
        await svc.verify_and_consume(token, make_order())
    assert _fail(exc) is TokenFailure.MISSING


@pytest.mark.parametrize("token", ["garbage", "v2.a.b", "v1.only-two"])
def test_malformed(svc: ApprovalTokenService, token: str) -> None:
    with pytest.raises(ApprovalTokenError) as exc:
        svc.verify(token, make_order())
    assert _fail(exc) is TokenFailure.MALFORMED


def test_tampered_signature_and_claims(svc: ApprovalTokenService) -> None:
    order = make_order()
    token = svc.issue(order, "kashyap")
    v, body, sig = token.split(".")
    flipped = sig[:-1] + ("A" if sig[-1] != "A" else "B")
    with pytest.raises(ApprovalTokenError) as exc:
        svc.verify(f"{v}.{body}.{flipped}", order)
    assert _fail(exc) is TokenFailure.BAD_SIGNATURE

    claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    claims["exp"] = "2099-01-01T00:00:00+00:00"  # extend expiry without re-signing
    forged = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    with pytest.raises(ApprovalTokenError) as exc:
        svc.verify(f"{v}.{forged}.{sig}", order)
    assert _fail(exc) is TokenFailure.BAD_SIGNATURE


def test_signed_but_unparseable_claims(svc: ApprovalTokenService) -> None:
    body = "v1." + base64.urlsafe_b64encode(b'{"pid": 1}').rstrip(b"=").decode()
    token = f"{body}.{svc._sign(body)}"
    with pytest.raises(ApprovalTokenError) as exc:
        svc.verify(token, make_order())
    assert _fail(exc) is TokenFailure.MALFORMED


def test_token_from_other_secret_rejected(clock: FrozenClock) -> None:
    other = ApprovalTokenService("another-secret-0123456789abcdef", clock, InMemoryNonceStore())
    order = make_order()
    with pytest.raises(ApprovalTokenError) as exc:
        ApprovalTokenService(SECRET, clock, InMemoryNonceStore()).verify(other.issue(order, "x"), order)
    assert _fail(exc) is TokenFailure.BAD_SIGNATURE


def test_order_tamper_detected(svc: ApprovalTokenService) -> None:
    order = make_order()
    token = svc.issue(order, "kashyap")
    for changed in (
        order.model_copy(update={"quantity": 150}),
        order.model_copy(update={"limit_price": Decimal("24000")}),
        order.model_copy(update={"client_order_id": "other"}),
    ):
        with pytest.raises(ApprovalTokenError) as exc:
            svc.verify(token, changed)
        assert _fail(exc) is TokenFailure.ORDER_MISMATCH


async def test_replay_rejected(svc: ApprovalTokenService) -> None:
    order = make_order()
    token = svc.issue(order, "kashyap")
    await svc.verify_and_consume(token, order)
    with pytest.raises(ApprovalTokenError) as exc:
        await svc.verify_and_consume(token, order)
    assert _fail(exc) is TokenFailure.REPLAYED


async def test_expiry(svc: ApprovalTokenService, clock: FrozenClock) -> None:
    order = make_order()
    token = svc.issue(order, "kashyap")
    clock.advance(seconds=299)
    svc.verify(token, order)
    clock.advance(seconds=1)
    with pytest.raises(ApprovalTokenError) as exc:
        await svc.verify_and_consume(token, order)
    assert _fail(exc) is TokenFailure.EXPIRED


def test_future_issued_token_rejected(clock: FrozenClock) -> None:
    order = make_order()
    future = FrozenClock(clock.now() + timedelta(minutes=1))
    token = ApprovalTokenService(SECRET, future, InMemoryNonceStore()).issue(order, "k")
    with pytest.raises(ApprovalTokenError) as exc:
        ApprovalTokenService(SECRET, clock, InMemoryNonceStore()).verify(token, order)
    assert _fail(exc) is TokenFailure.NOT_YET_VALID


def test_short_secret_refused(clock: FrozenClock) -> None:
    with pytest.raises(ConfigError):
        ApprovalTokenService("short", clock, InMemoryNonceStore())


async def test_redis_nonce_store_single_use(clock: FrozenClock) -> None:
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    store = RedisNonceStore(redis)
    exp = clock.now() + timedelta(minutes=5)
    assert await store.consume("n1", exp)
    assert not await store.consume("n1", exp)
    assert await store.consume("n2", exp)
    await redis.aclose()


def _proposal(clock: FrozenClock, **kw: object) -> Proposal:
    data: dict[str, object] = {
        "id": "prop_1",
        "created_at": clock.now(),
        "valid_until": clock.now() + timedelta(minutes=5),
        "horizon": Horizon.INTRADAY,
        "underlying": "NIFTY",
        "legs": (make_order(),),
        "status": ProposalStatus.PENDING_APPROVAL,
    }
    data.update(kw)
    return Proposal(**data)  # type: ignore[arg-type]


async def test_approval_service_issues_bound_tokens(
    svc: ApprovalTokenService, clock: FrozenClock
) -> None:
    audit = InMemoryAuditLog(clock)
    proposal = _proposal(clock)
    approved, tokens = await ApprovalService(svc, audit, clock).approve(proposal, "kashyap", "api")
    assert approved.status is ProposalStatus.APPROVED
    leg = proposal.legs[0]
    claims = svc.verify(tokens[leg.client_order_id], leg)
    assert claims.expires_at == proposal.valid_until
    assert audit.of_type("proposal.approved")[0].payload["order_hashes"] == [leg.payload_hash()]


async def test_approval_after_validity_window_rejected(
    svc: ApprovalTokenService, clock: FrozenClock
) -> None:
    audit = InMemoryAuditLog(clock)
    proposal = _proposal(clock)
    clock.advance(minutes=5)
    with pytest.raises(InvalidTransitionError, match="expired"):
        await ApprovalService(svc, audit, clock).approve(proposal, "kashyap", "telegram")
    assert audit.of_type("proposal.expired")


async def test_reject_and_lifecycle_rules(svc: ApprovalTokenService, clock: FrozenClock) -> None:
    audit = InMemoryAuditLog(clock)
    rejected = await ApprovalService(svc, audit, clock).reject(_proposal(clock), "kashyap", "no")
    assert rejected.status is ProposalStatus.REJECTED
    with pytest.raises(InvalidTransitionError):
        transition(rejected, ProposalStatus.APPROVED)
    draft = _proposal(clock, status=ProposalStatus.DRAFT)
    with pytest.raises(InvalidTransitionError):
        transition(draft, ProposalStatus.EXECUTED)
    assert transition(draft, ProposalStatus.PENDING_APPROVAL).status is ProposalStatus.PENDING_APPROVAL
