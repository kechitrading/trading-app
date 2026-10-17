"""Placeholder scheduled jobs. Each only logs and writes an audit event for now."""

from __future__ import annotations

from typing import Any

from aqta.audit import AuditSink
from aqta.core.logs import get_logger

log = get_logger(__name__)


async def _placeholder(ctx: dict[str, Any], job: str, brd: str) -> str:
    audit: AuditSink = ctx["audit"]
    log.info("job.run", job=job, brd=brd, status="placeholder")
    await audit.record("job.ran", {"job": job, "brd": brd, "status": "placeholder"}, "worker")
    return job


async def pre_market_brief(ctx: dict[str, Any]) -> str:
    """FR-038: pre-market brief by 08:45 IST. TODO: build and deliver the brief."""
    return await _placeholder(ctx, "pre_market_brief", "FR-038")


async def post_market_review(ctx: dict[str, Any]) -> str:
    """FR-039: equity and derivatives review by 17:00 IST."""
    return await _placeholder(ctx, "post_market_review", "FR-039")


async def mcx_wrap(ctx: dict[str, Any]) -> str:
    """FR-039: MCX commodity wrap by 23:45 IST."""
    return await _placeholder(ctx, "mcx_wrap", "FR-039")


async def monthly_astrology_study(ctx: dict[str, Any]) -> str:
    """FR-074, FR-076: re-run astrology studies monthly and report (shadow mode only)."""
    return await _placeholder(ctx, "monthly_astrology_study", "FR-074")


async def weekly_learning_proposal(ctx: dict[str, Any]) -> str:
    """FR-047: weekly learned-change proposals with out-of-sample evidence, for approval."""
    return await _placeholder(ctx, "weekly_learning_proposal", "FR-047")
