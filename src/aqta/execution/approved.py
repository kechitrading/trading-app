"""Send an approved proposal's legs through the gateway, paper mode only (FR-025, FR-030).

In Phase 1 live mode the system never sends orders (CR-003, RULE-016): Kashyap places them from an
order ticket. This helper therefore refuses anything but paper mode.
"""

from __future__ import annotations

from aqta.core.errors import SafetyViolationError
from aqta.core.settings import TradingMode
from aqta.core.trading import OrderRequest, RiskEffect
from aqta.execution.gateway import OrderGateway, OrderResult


def leg_order(legs: tuple[OrderRequest, ...]) -> list[OrderRequest]:
    """FR-025: risk-reducing legs (hedges, exits) go first; otherwise the proposal's order."""
    return sorted(legs, key=lambda leg: leg.risk_effect is not RiskEffect.REDUCING)


async def execute_paper(
    gateway: OrderGateway, legs: tuple[OrderRequest, ...], tokens: dict[str, str]
) -> list[OrderResult]:
    """Submit each leg with its own approval token; stop at the first leg that is not accepted,
    so a hedge-first sequence never leaves an unhedged leg behind."""
    if gateway.mode is not TradingMode.PAPER:
        raise SafetyViolationError("Phase 1 sends no live orders (CR-003); use an order ticket")
    results: list[OrderResult] = []
    for leg in leg_order(legs):
        result = await gateway.submit_order(leg, tokens.get(leg.client_order_id))
        results.append(result)
        if not result.accepted:
            break
    return results
