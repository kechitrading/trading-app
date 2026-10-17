"""Astrology rule registry and accuracy gate (FR-071..FR-076, RULE-014, RULE-015, ASM-013).

No business rules live here yet: only the lifecycle and the zero-weight guarantee.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aqta.core.errors import InvalidTransitionError
from aqta.core.settings import AstrologySettings


class RuleFamily(StrEnum):
    SARVATOBHADRA = "sarvatobhadra"
    MUNDANE = "mundane"


class RuleOrigin(StrEnum):
    SEED = "seed"  # supplied by Kashyap or a named astrologer (Q-006)
    DISCOVERED = "discovered"  # data-driven search within pre-registered families (FR-071)


class RuleStatus(StrEnum):
    CANDIDATE = "candidate"
    SHADOW = "shadow"
    ACTIVE = "active"
    DEMOTED = "demoted"
    RETIRED = "retired"


_ALLOWED: dict[RuleStatus, frozenset[RuleStatus]] = {
    RuleStatus.CANDIDATE: frozenset({RuleStatus.SHADOW, RuleStatus.RETIRED}),
    RuleStatus.SHADOW: frozenset({RuleStatus.ACTIVE, RuleStatus.RETIRED}),
    RuleStatus.ACTIVE: frozenset({RuleStatus.DEMOTED, RuleStatus.RETIRED}),
    RuleStatus.DEMOTED: frozenset({RuleStatus.SHADOW, RuleStatus.RETIRED}),
    RuleStatus.RETIRED: frozenset(),
}


class GateResult(BaseModel):
    """Outcome of the ASM-013 accuracy gate for one rule (filled by the study runner, FR-072)."""

    hypotheses_tried: int = Field(ge=1)
    fdr_significant: bool
    oos_events: int = Field(ge=0)
    oos_net_edge_positive: bool
    oos_hit_rate: float = Field(ge=0, le=1)
    beats_baseline: bool
    beats_shuffled_controls: bool

    def passes(self, cfg: AstrologySettings) -> bool:
        return (
            self.fdr_significant
            and self.oos_events >= cfg.gate_min_oos_events
            and self.oos_net_edge_positive
            and self.oos_hit_rate >= cfg.gate_min_hit_rate
            and self.beats_baseline
            and self.beats_shuffled_controls
        )


class AstrologyRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    family: RuleFamily
    origin: RuleOrigin
    version: int = 1
    status: RuleStatus = RuleStatus.CANDIDATE
    weight: float = 0.0
    hypothesis: dict[str, Any] = Field(default_factory=dict)  # recorded before testing (RULE-015)
    gate: GateResult | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None

    @property
    def approved(self) -> bool:
        return self.approved_by is not None and self.approved_at is not None


def effective_weight(rule: AstrologyRule | None, cfg: AstrologySettings) -> float:
    """RULE-014 / FR-073: zero unless active, gate-passed, approved and global shadow mode off."""
    if rule is None or cfg.shadow_mode:
        return 0.0
    if rule.status is not RuleStatus.ACTIVE or not rule.approved:
        return 0.0
    if rule.gate is None or not rule.gate.passes(cfg):
        return 0.0
    return rule.weight


def change_status(
    rule: AstrologyRule,
    to: RuleStatus,
    cfg: AstrologySettings,
    *,
    approved_by: str | None = None,
    at: datetime | None = None,
    weight: float | None = None,
) -> AstrologyRule:
    if to not in _ALLOWED[rule.status]:
        raise InvalidTransitionError(f"astrology rule {rule.id}: {rule.status} -> {to}")
    updates: dict[str, Any] = {"status": to}
    if to is RuleStatus.ACTIVE:
        if rule.gate is None or not rule.gate.passes(cfg):
            raise InvalidTransitionError(f"rule {rule.id} has not passed the accuracy gate")
        if not approved_by or at is None:
            raise InvalidTransitionError(f"rule {rule.id} needs Kashyap's approval (Q-017)")
        updates |= {"approved_by": approved_by, "approved_at": at, "weight": weight or 0.0}
    else:
        updates["weight"] = 0.0  # any non-active status forces zero weight
    return rule.model_copy(update=updates)
