"""Reports (BR-007, BR-008, FR-038..FR-045, FR-065): types, template registry, rationale-pack
builder and export interfaces. Every report carries the proposals-not-guarantees disclaimer.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field

DISCLAIMER = (
    "For Kashyap's personal use only (RULE-008). Outputs are proposals and estimates, "
    "not guarantees."
)


class ReportType(StrEnum):
    PRE_MARKET = "pre_market"  # FR-038, by 08:45 IST
    POST_MARKET = "post_market"  # FR-039, by 17:00 IST
    MCX_WRAP = "mcx_wrap"  # FR-039, by 23:45 IST
    DEEP_DIVE = "deep_dive"  # FR-040 short/long
    STRATEGY_ARBITRAGE = "strategy_arbitrage"  # FR-041
    PERFORMANCE_LEARNING = "performance_learning"  # FR-042
    ASTROLOGY_STUDY = "astrology_study"  # FR-076
    RATIONALE_PACK = "rationale_pack"  # FR-043


class ExportFormat(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    CSV = "csv"  # FR-054 trade/P&L export


class Report(BaseModel):
    type: ReportType
    title: str
    generated_at: datetime
    sections: dict[str, Any] = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)
    disclaimer: str = DISCLAIMER


class RationalePack(BaseModel):
    """FR-043: created at proposal, frozen at approval, updated at adjustments and exit."""

    trade_id: str
    proposal_id: str
    signals: dict[str, Any] = Field(default_factory=dict)
    data_snapshot: dict[str, Any] = Field(default_factory=dict)
    risk: dict[str, Any] = Field(default_factory=dict)
    hedge: dict[str, Any] = Field(default_factory=dict)
    approval: dict[str, Any] | None = None
    outcome: dict[str, Any] | None = None
    frozen_at: datetime | None = None
    versions: dict[str, str] = Field(default_factory=dict)  # NFR-016 model/rule versions


class TemplateRegistry:
    def __init__(self) -> None:
        self._templates: dict[ReportType, str] = {}

    def register(self, report_type: ReportType, template: str) -> None:
        self._templates[report_type] = template

    def get(self, report_type: ReportType) -> str:
        return self._templates[report_type]


class Exporter(Protocol):
    def export(self, report: Report, fmt: ExportFormat) -> bytes: ...


__all__ = [
    "DISCLAIMER",
    "ExportFormat",
    "Exporter",
    "RationalePack",
    "Report",
    "ReportType",
    "TemplateRegistry",
]
