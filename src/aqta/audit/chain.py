"""Hash-chain primitives for the append-only audit log (FR-054, NFR-011).

Each entry's hash is SHA-256 over ``prev_hash`` plus the canonical JSON of its content, so changing,
removing or inserting any row breaks every later link.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from aqta.core.hashing import canonical_json, sha256_hex, to_jsonable
from aqta.core.timeutil import ensure_utc

GENESIS_HASH = "0" * 64


def normalize_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Make a payload stable across a JSONB round trip.

    Floats become strings (JSONB re-renders numbers, e.g. ``1e16`` -> ``10000000000000000``, which
    would change the hash). Use Decimal or str for money anyway.
    """

    def walk(value: Any) -> Any:
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("Audit payloads cannot contain NaN/inf")
            return repr(value)
        if isinstance(value, dict):
            return {str(k): walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value

    result = walk(to_jsonable(dict(payload)))
    assert isinstance(result, dict)
    return result


def compute_hash(
    prev_hash: str, occurred_at: datetime, event_type: str, actor: str, payload: Mapping[str, Any]
) -> str:
    body = canonical_json(
        {
            "occurred_at": ensure_utc(occurred_at).isoformat(),
            "event_type": event_type,
            "actor": actor,
            "payload": payload,
        }
    )
    return sha256_hex(f"{prev_hash}|{body}")


@dataclass(frozen=True, slots=True)
class AuditEntry:
    seq: int
    occurred_at: datetime
    event_type: str
    actor: str
    payload: dict[str, Any]
    prev_hash: str
    hash: str


@dataclass(slots=True)
class ChainVerification:
    ok: bool
    checked: int
    head_hash: str
    errors: list[str] = field(default_factory=list)


def verify_chain(entries: Iterable[AuditEntry]) -> ChainVerification:
    """Recompute every link in ``seq`` order. Reports all broken links, not just the first."""
    expected_prev = GENESIS_HASH
    errors: list[str] = []
    count = 0
    for entry in entries:
        count += 1
        if entry.prev_hash != expected_prev:
            errors.append(f"seq={entry.seq}: prev_hash does not match previous entry (broken link)")
        recomputed = compute_hash(
            entry.prev_hash, entry.occurred_at, entry.event_type, entry.actor, entry.payload
        )
        if recomputed != entry.hash:
            errors.append(f"seq={entry.seq}: content hash mismatch (row altered)")
        expected_prev = entry.hash
    return ChainVerification(ok=not errors, checked=count, head_hash=expected_prev, errors=errors)
