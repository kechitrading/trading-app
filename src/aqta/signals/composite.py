"""Composite signal: per-component value, weight and contribution are always visible (FR-009).

Astrology components get an effective weight of 0 unless their governing rule is active, passed the
gate and was approved (RULE-014, FR-073). Degraded components are excluded (FR-004).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from aqta.astrology import AstrologyRule, effective_weight
from aqta.core.settings import AstrologySettings
from aqta.signals.base import ComponentFamily, ComponentValue


class WeightSet(BaseModel):
    """Versioned weights (FR-047, FR-048). Changes need approval and are reversible."""

    model_config = ConfigDict(frozen=True)

    version: str
    weights: dict[str, float] = Field(default_factory=dict)


DEFAULT_WEIGHTS = WeightSet(
    version="baseline-0",
    weights={
        ComponentFamily.NEWS_SENTIMENT.value: 0.25,
        ComponentFamily.QUANT_TECHNICAL.value: 0.35,
        ComponentFamily.INSTITUTIONAL_FLOW.value: 0.2,
        ComponentFamily.FUNDAMENTAL.value: 0.2,
        ComponentFamily.ASTROLOGY_SARVATOBHADRA.value: 0.0,
        ComponentFamily.ASTROLOGY_MUNDANE.value: 0.0,
    },
)


class Contribution(BaseModel):
    model_config = ConfigDict(frozen=True)

    component: str
    family: ComponentFamily
    value: float
    confidence: float
    configured_weight: float
    effective_weight: float
    contribution: float
    shadow: bool = False
    excluded_reason: str | None = None


class CompositeResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    as_of: datetime
    score: float  # weighted mean of included components, in [-1, 1]
    weight_set_version: str
    contributions: tuple[Contribution, ...]

    def top(self, n: int = 3) -> list[Contribution]:
        """FR-010: top contributing signals by absolute contribution."""
        return sorted(self.contributions, key=lambda c: abs(c.contribution), reverse=True)[:n]


def combine(
    symbol: str,
    as_of: datetime,
    values: Sequence[ComponentValue],
    weights: WeightSet,
    astrology_cfg: AstrologySettings,
    astrology_rules: Mapping[str, AstrologyRule | None] | None = None,
) -> CompositeResult:
    rules = astrology_rules or {}
    contributions: list[Contribution] = []
    for v in values:
        configured = weights.weights.get(v.component, 0.0)
        shadow = False
        reason: str | None = None
        if v.family.is_astrology:
            eff = effective_weight(rules.get(v.component), astrology_cfg)
            if eff == 0.0:
                shadow, reason = True, "shadow mode: rule not active/approved (RULE-014)"
        else:
            eff = configured
        if v.degraded:
            eff, reason = 0.0, "degraded data (FR-004)"
        contributions.append(
            Contribution(
                component=v.component,
                family=v.family,
                value=v.value,
                confidence=v.confidence,
                configured_weight=configured,
                effective_weight=eff,
                contribution=eff * v.value,
                shadow=shadow,
                excluded_reason=reason,
            )
        )
    total = sum(c.effective_weight for c in contributions)
    score = sum(c.contribution for c in contributions) / total if total > 0 else 0.0
    return CompositeResult(
        symbol=symbol,
        as_of=as_of,
        score=score,
        weight_set_version=weights.version,
        contributions=tuple(contributions),
    )
