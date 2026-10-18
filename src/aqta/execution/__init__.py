"""Order execution (BR-003, FR-024..FR-030). Safety-critical; mypy strict; >= 90% coverage.

Public API:
- ``OrderGateway.submit_order(order, approval_token)``: the only way to reach a broker
- ``BrokerPort`` (abstract), ``PaperBroker``, ``LiveBrokerStub`` (raises, Q-005)
- ``OrderState``/``OrderEvent`` state machine, ``Reconciler`` interface (FR-027)

Never imports signals, forecasting, astrology or analysis (RULE-013).
"""

from aqta.execution.approved import execute_paper, leg_order
from aqta.execution.gateway import (
    ManagedOrder,
    OrderGateway,
    OrderResult,
    Stage,
    select_broker,
)
from aqta.execution.live import LiveBrokerStub
from aqta.execution.paper import FixedBpsSlippage, PaperBroker, ZeroCost
from aqta.execution.ports import (
    BrokerAck,
    BrokerError,
    BrokerOrderSnapshot,
    BrokerOrderStatus,
    BrokerPort,
    BrokerPosition,
    Reconciler,
    ReconciliationReport,
)
from aqta.execution.states import TERMINAL, OrderEvent, OrderState, is_open, next_state

__all__ = [
    "TERMINAL",
    "BrokerAck",
    "BrokerError",
    "BrokerOrderSnapshot",
    "BrokerOrderStatus",
    "BrokerPort",
    "BrokerPosition",
    "FixedBpsSlippage",
    "LiveBrokerStub",
    "ManagedOrder",
    "OrderEvent",
    "OrderGateway",
    "OrderResult",
    "OrderState",
    "PaperBroker",
    "Reconciler",
    "ReconciliationReport",
    "Stage",
    "ZeroCost",
    "execute_paper",
    "is_open",
    "leg_order",
    "next_state",
    "select_broker",
]
