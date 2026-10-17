"""FR-009 visibility and RULE-014 / FR-073 zero astrology contribution."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from aqta.astrology import (
    AstrologyRule,
    GateResult,
    RuleFamily,
    RuleOrigin,
    RuleStatus,
    change_status,
    effective_weight,
)
from aqta.core.errors import InvalidTransitionError
from aqta.core.settings import AstrologySettings
from aqta.signals import (
    DEFAULT_WEIGHTS,
    ComponentFamily,
    ComponentValue,
    WeightSet,
    combine,
    default_components,
)

NOW = datetime(2026, 10, 20, 4, 30, tzinfo=UTC)
F = ComponentFamily
PASSING_GATE = GateResult(
    hypotheses_tried=40,
    fdr_significant=True,
    oos_events=35,
    oos_net_edge_positive=True,
    oos_hit_rate=0.62,
    beats_baseline=True,
    beats_shuffled_controls=True,
)


def cv(family: ComponentFamily, value: float, **kw: object) -> ComponentValue:
    return ComponentValue(component=family.value, family=family, value=value, as_of=NOW, **kw)  # type: ignore[arg-type]


def all_values(astro_value: float = 1.0) -> list[ComponentValue]:
    return [
        cv(F.NEWS_SENTIMENT, 0.5, confidence=0.7),
        cv(F.QUANT_TECHNICAL, -0.2),
        cv(F.INSTITUTIONAL_FLOW, 0.1),
        cv(F.FUNDAMENTAL, 0.0),
        cv(F.ASTROLOGY_SARVATOBHADRA, astro_value),
        cv(F.ASTROLOGY_MUNDANE, astro_value),
    ]


GREEDY = WeightSet(version="t1", weights={f.value: 0.5 for f in F})  # asks for astro weight too


def rule(status: RuleStatus = RuleStatus.SHADOW, **kw: object) -> AstrologyRule:
    data: dict[str, object] = {
        "id": "r1",
        "family": RuleFamily.MUNDANE,
        "origin": RuleOrigin.SEED,
        "status": status,
    }
    data.update(kw)
    return AstrologyRule(**data)  # type: ignore[arg-type]


def test_every_component_shows_value_weight_contribution() -> None:
    res = combine("NIFTY", NOW, all_values(), DEFAULT_WEIGHTS, AstrologySettings())
    assert [c.component for c in res.contributions] == [f.value for f in F]
    news = res.contributions[0]
    assert (news.value, news.configured_weight, news.effective_weight) == (0.5, 0.25, 0.25)
    assert news.contribution == pytest.approx(0.125)
    assert res.weight_set_version == "baseline-0"
    assert res.top(1)[0].component == "news_sentiment"


def test_astrology_contributes_zero_in_shadow_mode_even_if_weight_requested() -> None:
    cfg = AstrologySettings()
    rules = {F.ASTROLOGY_MUNDANE.value: rule(), F.ASTROLOGY_SARVATOBHADRA.value: None}
    with_astro = combine("NIFTY", NOW, all_values(1.0), GREEDY, cfg, rules)
    without = combine("NIFTY", NOW, all_values(-1.0), GREEDY, cfg, rules)
    for c in with_astro.contributions:
        if c.family.is_astrology:
            assert c.configured_weight == 0.5
            assert c.effective_weight == 0.0 and c.contribution == 0.0 and c.shadow
            assert "RULE-014" in (c.excluded_reason or "")
    assert with_astro.score == without.score  # astrology value cannot move the composite


@given(st.floats(min_value=-1, max_value=1), st.sampled_from(list(RuleStatus)))
def test_property_astrology_zero_unless_active_and_approved(
    value: float, status: RuleStatus
) -> None:
    cfg = AstrologySettings(shadow_mode=False)
    r = rule(status, weight=0.0, gate=PASSING_GATE)  # not approved
    res = combine(
        "X", NOW, [cv(F.ASTROLOGY_MUNDANE, value)], GREEDY, cfg, {F.ASTROLOGY_MUNDANE.value: r}
    )
    assert res.contributions[0].contribution == 0.0
    assert res.score == 0.0


def test_astrology_counts_only_when_active_gated_approved_and_global_shadow_off() -> None:
    shadow = rule(RuleStatus.SHADOW, gate=PASSING_GATE)
    active = change_status(
        shadow, RuleStatus.ACTIVE, AstrologySettings(), approved_by="kashyap", at=NOW, weight=0.1
    )
    assert active.approved and active.weight == 0.1
    # Global shadow switch still on -> zero.
    assert effective_weight(active, AstrologySettings()) == 0.0
    cfg = AstrologySettings(shadow_mode=False)
    assert effective_weight(active, cfg) == 0.1
    res = combine(
        "X", NOW, [cv(F.ASTROLOGY_MUNDANE, 1.0)], GREEDY, cfg, {F.ASTROLOGY_MUNDANE.value: active}
    )
    assert res.contributions[0].contribution == pytest.approx(0.1)
    assert not res.contributions[0].shadow


def test_activation_requires_gate_and_approval() -> None:
    cfg = AstrologySettings()
    failing = PASSING_GATE.model_copy(update={"oos_events": 10})
    with pytest.raises(InvalidTransitionError, match="gate"):
        change_status(rule(gate=failing), RuleStatus.ACTIVE, cfg, approved_by="k", at=NOW)
    with pytest.raises(InvalidTransitionError, match="gate"):
        change_status(rule(), RuleStatus.ACTIVE, cfg, approved_by="k", at=NOW)
    with pytest.raises(InvalidTransitionError, match="approval"):
        change_status(rule(gate=PASSING_GATE), RuleStatus.ACTIVE, cfg)
    with pytest.raises(InvalidTransitionError):
        change_status(rule(RuleStatus.CANDIDATE), RuleStatus.ACTIVE, cfg)


def test_demotion_forces_zero_weight() -> None:
    cfg = AstrologySettings()
    active = change_status(
        rule(gate=PASSING_GATE), RuleStatus.ACTIVE, cfg, approved_by="k", at=NOW, weight=0.2
    )
    demoted = change_status(active, RuleStatus.DEMOTED, cfg)
    assert demoted.weight == 0.0
    assert effective_weight(demoted, AstrologySettings(shadow_mode=False)) == 0.0
    with pytest.raises(InvalidTransitionError):
        change_status(change_status(demoted, RuleStatus.RETIRED, cfg), RuleStatus.SHADOW, cfg)


def test_degraded_component_excluded() -> None:
    res = combine(
        "X",
        NOW,
        [cv(F.NEWS_SENTIMENT, 1.0, degraded=True), cv(F.QUANT_TECHNICAL, 0.5)],
        DEFAULT_WEIGHTS,
        AstrologySettings(),
    )
    assert res.contributions[0].effective_weight == 0.0
    assert res.contributions[0].excluded_reason == "degraded data (FR-004)"
    assert res.score == pytest.approx(0.5)


def test_no_weight_gives_neutral_score() -> None:
    assert combine("X", NOW, [], DEFAULT_WEIGHTS, AstrologySettings()).score == 0.0


async def test_stub_components_are_neutral() -> None:
    comps = default_components()
    assert {c.family for c in comps} == set(F)
    for comp in comps:
        out = await comp.compute("NIFTY", NOW)
        assert out.value == 0.0 and out.evidence == (f"stub:{comp.name}",)
