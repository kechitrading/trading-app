from __future__ import annotations

import dataclasses
import itertools
from decimal import Decimal

import pytest

from aqta.audit import GENESIS_HASH, InMemoryAuditLog, verify_chain
from aqta.audit.chain import normalize_payload
from aqta.core.clock import FrozenClock


async def _log_with(n: int, clock: FrozenClock) -> InMemoryAuditLog:
    log = InMemoryAuditLog(clock)
    for i in range(n):
        clock.advance(seconds=1)
        await log.record("test.event", {"i": i, "amount": Decimal("10.50")}, actor="tester")
    return log


async def test_chain_links_and_verifies(clock: FrozenClock) -> None:
    log = await _log_with(5, clock)
    entries = log.entries
    assert entries[0].prev_hash == GENESIS_HASH
    for prev, cur in itertools.pairwise(entries):
        assert cur.prev_hash == prev.hash
    result = log.verify()
    assert result.ok and result.checked == 5 and result.head_hash == entries[-1].hash
    assert log.of_type("test.event") == entries


async def test_empty_chain_is_valid() -> None:
    result = verify_chain([])
    assert result.ok and result.checked == 0 and result.head_hash == GENESIS_HASH


async def test_modified_payload_detected(clock: FrozenClock) -> None:
    entries = (await _log_with(4, clock)).entries
    entries[1] = dataclasses.replace(entries[1], payload={"i": 999})
    result = verify_chain(entries)
    assert not result.ok
    assert any("seq=2" in e and "altered" in e for e in result.errors)


async def test_deleted_row_detected(clock: FrozenClock) -> None:
    entries = (await _log_with(4, clock)).entries
    del entries[1]
    result = verify_chain(entries)
    assert not result.ok
    assert any("broken link" in e for e in result.errors)


async def test_rehashed_row_still_breaks_next_link(clock: FrozenClock) -> None:
    """An attacker who recomputes one row's hash still breaks the following prev_hash link."""
    from aqta.audit import compute_hash

    entries = (await _log_with(3, clock)).entries
    e = entries[1]
    forged = dataclasses.replace(
        e,
        payload={"i": -1},
        hash=compute_hash(e.prev_hash, e.occurred_at, e.event_type, e.actor, {"i": -1}),
    )
    entries[1] = forged
    result = verify_chain(entries)
    assert not result.ok
    assert any("seq=3" in err for err in result.errors)


def test_payload_normalisation() -> None:
    out = normalize_payload({"f": 1e16, "d": Decimal("1.10"), "nested": [{"x": 0.1}]})
    assert out == {"f": "1e+16", "d": "1.10", "nested": [{"x": "0.1"}]}
    with pytest.raises(ValueError, match="NaN"):
        normalize_payload({"bad": float("nan")})
