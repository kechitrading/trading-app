"""Learning governance (BR-010, FR-047..FR-050, RULE-006): proposed changes need out-of-sample
evidence and Kashyap's approval, and every version can be rolled back within 10 minutes (FR-048).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field

from aqta.core.errors import InvalidTransitionError


class ConfigKind(StrEnum):
    SIGNAL_WEIGHTS = "signal_weights"
    RISK_LIMITS = "risk_limits"
    MODEL = "model"
    ASTROLOGY_RULESET = "astrology_ruleset"


class ChangeStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    ROLLED_BACK = "rolled_back"


_ALLOWED = {
    ChangeStatus.PROPOSED: {ChangeStatus.APPROVED, ChangeStatus.REJECTED},
    ChangeStatus.APPROVED: {ChangeStatus.APPLIED},
    ChangeStatus.APPLIED: {ChangeStatus.ROLLED_BACK},
}


class LearnedChange(BaseModel):
    id: str
    kind: ConfigKind
    from_version: int
    to_version: int
    payload: dict[str, Any]
    evidence: dict[str, Any] = Field(default_factory=dict)  # out-of-sample results (FR-047)
    status: ChangeStatus = ChangeStatus.PROPOSED
    proposed_at: datetime
    approved_by: str | None = None


def advance(change: LearnedChange, to: ChangeStatus, actor: str | None = None) -> LearnedChange:
    if to not in _ALLOWED.get(change.status, set()):
        raise InvalidTransitionError(f"learned change {change.id}: {change.status} -> {to}")
    if to is ChangeStatus.APPROVED and not change.evidence:
        raise InvalidTransitionError("out-of-sample evidence required before approval (FR-047)")
    update: dict[str, Any] = {"status": to}
    if to is ChangeStatus.APPROVED:
        update["approved_by"] = actor
    return change.model_copy(update=update)


class VersionStore(Protocol):
    """Backed by ``config_versions``. Rollback = re-activate a previous version (FR-048)."""

    async def active(self, kind: ConfigKind) -> int | None: ...

    async def activate(self, kind: ConfigKind, version: int, actor: str) -> None: ...


__all__ = ["ChangeStatus", "ConfigKind", "LearnedChange", "VersionStore", "advance"]
