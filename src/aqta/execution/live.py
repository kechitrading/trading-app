"""Placeholder for the real broker adapter. Intentionally unimplemented.

Do not add live-order code without an explicit instruction from Kashyap (see CLAUDE.md). The broker
is Angel One SmartAPI (Q-005, decided 2026-10-18), and live trading also needs the
static IP (NFR-010), daily 2FA login (FR-029) and the algo identifier (FR-028, Q-008).
"""

from __future__ import annotations

from decimal import Decimal

from aqta.core.trading import OrderRequest
from aqta.execution.ports import BrokerAck, BrokerOrderSnapshot, BrokerPort, BrokerPosition

_MSG = (
    "Live broker adapter not implemented (Angel One SmartAPI, BRD Q-005). "
    "Implement a BrokerPort adapter only after Kashyap explicitly approves live-order code."
)


class LiveBrokerStub(BrokerPort):
    name = "live-stub"
    is_live = True

    async def place_order(self, order: OrderRequest, algo_tag: str) -> BrokerAck:
        raise NotImplementedError(_MSG)

    async def get_order(self, broker_order_id: str) -> BrokerOrderSnapshot:
        raise NotImplementedError(_MSG)

    async def cancel_order(self, broker_order_id: str) -> bool:
        raise NotImplementedError(_MSG)

    async def modify_order(
        self,
        broker_order_id: str,
        *,
        limit_price: Decimal | None = None,
        quantity: int | None = None,
    ) -> bool:
        raise NotImplementedError(_MSG)

    async def positions(self) -> list[BrokerPosition]:
        raise NotImplementedError(_MSG)
