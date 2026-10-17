"""Shared neutral stub used by every component until its feature ticket lands."""

from __future__ import annotations

from datetime import datetime

from aqta.signals.base import ComponentFamily, ComponentValue


class StubComponent:
    def __init__(self, family: ComponentFamily) -> None:
        self.family = family
        self.name = family.value

    async def compute(self, symbol: str, at: datetime) -> ComponentValue:
        return ComponentValue(
            component=self.name, family=self.family, value=0.0, confidence=0.0, as_of=at,
            evidence=(f"stub:{self.name}",),
        )
