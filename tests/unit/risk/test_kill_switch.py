from __future__ import annotations

import fakeredis
import pytest
from factories import RiskRig

from aqta.core.clock import FrozenClock
from aqta.risk import InMemoryKillSwitchStore, KillSwitch, KillSwitchState, RiskEventType
from aqta.risk.adapters import RedisKillSwitchStore


@pytest.fixture
def rig(clock: FrozenClock) -> RiskRig:
    return RiskRig(clock)


async def test_default_inactive(rig: RiskRig) -> None:
    assert not await rig.kill_switch.is_active()
    assert await rig.kill_switch.state() is None


async def test_trigger_and_release_are_audited(rig: RiskRig) -> None:
    calls: list[KillSwitchState] = []

    async def cancel_all(state: KillSwitchState) -> None:
        calls.append(state)

    rig.kill_switch.register_on_trigger(cancel_all)
    state = await rig.kill_switch.trigger("kashyap", "feed outage")
    assert state.active and await rig.kill_switch.is_active()
    assert calls == [state]
    assert rig.audit.of_type("kill_switch.triggered")[0].payload["reason"] == "feed outage"

    with pytest.raises(ValueError, match="reason"):
        await rig.kill_switch.release("kashyap", "")
    await rig.kill_switch.release("kashyap", "feed restored")
    assert not await rig.kill_switch.is_active()
    kinds = [e.event_type for e in rig.events.events]
    assert kinds == [RiskEventType.KILL_SWITCH_TRIGGERED, RiskEventType.KILL_SWITCH_RELEASED]
    assert rig.audit.verify().ok


async def test_failing_callback_does_not_undo_trigger(rig: RiskRig) -> None:
    async def boom(_: KillSwitchState) -> None:
        raise RuntimeError("broker down")

    rig.kill_switch.register_on_trigger(boom)
    await rig.kill_switch.trigger("system", "auto")
    assert await rig.kill_switch.is_active()


async def test_fails_closed_when_store_unreadable(rig: RiskRig) -> None:
    rig.ks_store.fail_reads = True
    assert await rig.kill_switch.is_active()
    assert rig.events.of_type(RiskEventType.KILL_SWITCH_STORE_ERROR)


async def test_durable_store_warms_fast_store(clock: FrozenClock) -> None:
    rig = RiskRig(clock)
    durable = InMemoryKillSwitchStore()
    durable.state = KillSwitchState(True, clock.now(), "kashyap", "set before restart")
    fast = InMemoryKillSwitchStore()
    ks = KillSwitch(fast, rig.audit, rig.events, clock, durable=durable)
    assert await ks.is_active()
    assert fast.state == durable.state
    await ks.release("kashyap", "ok")
    assert durable.state is not None and not durable.state.active


async def test_redis_store_round_trip(clock: FrozenClock) -> None:
    redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    store = RedisKillSwitchStore(redis)
    assert await store.get() is None
    state = KillSwitchState(True, clock.now(), "kashyap", "why")
    await store.set(state)
    assert await store.get() == state
    await redis.aclose()
