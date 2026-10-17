"""Ports for the astrology research engine.

Adapters (pyswisseph etc.) come later (FR-005, FR-055).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol

from pydantic import BaseModel

from aqta.astrology.registry import AstrologyRule, GateResult


class PlanetPosition(BaseModel):
    body: str  # e.g. "Saturn", "Rahu"
    longitude_deg: float  # sidereal longitude
    nakshatra: str | None = None
    retrograde: bool = False


class EphemerisPort(Protocol):
    """Planetary positions for an instant (computed in UTC, displayed in IST)."""

    def positions(self, at: datetime) -> list[PlanetPosition]: ...


class MundaneEvent(BaseModel):
    """FR-055: dated ingress/transit/eclipse/lunation event with the rule that produced it."""

    on: date
    kind: str
    description: str
    rule_id: str
    rule_set_version: str


class StudyReport(BaseModel):
    """FR-070, FR-076: reproducible from stored data, rule version and random seed (NFR-023)."""

    rule_id: str
    rule_version: int
    seed: int
    sample_size: int
    gate: GateResult
    notes: str = ""


class StudyRunner(Protocol):
    async def run(self, rule: AstrologyRule, seed: int) -> StudyReport: ...
