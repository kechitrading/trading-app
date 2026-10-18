"""The sample proposal in scripts/try_bot.py passes risk checks and fills on paper."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from aqta.api import build_in_memory_container
from aqta.api.actions import ContainerBotActions
from aqta.core.clock import FrozenClock
from aqta.core.settings import Settings
from aqta.notifications import BotController, ProposalCb
from aqta.proposals import ProposalStatus

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "try_bot.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("try_bot", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_sample_proposal_approves_and_fills(settings: Settings, clock: FrozenClock) -> None:
    c = build_in_memory_container(settings, clock)
    p = await c.proposals.submit(_load().sample_proposal(clock))
    assert p.sets == 2
    bot = BotController(ContainerBotActions(c))
    reply = await bot.on_callback(ProposalCb(action="ac", pid=p.id))
    assert "Paper orders filled." in reply.text, reply.text
    assert (await c.proposals.get(p.id)).status is ProposalStatus.EXECUTED


async def test_sample_proposal_can_be_halved(settings: Settings, clock: FrozenClock) -> None:
    c = build_in_memory_container(settings, clock)
    p = await c.proposals.submit(_load().sample_proposal(clock))
    smaller = await c.proposals.modify(p.id, "kashyap", 1)
    assert [leg.lots for leg in smaller.legs] == [1, 1]
