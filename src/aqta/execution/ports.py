"""Broker port (hexagonal edge). Broker choice is open (Q-005), so nothing else knows a broker API."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from aqta.core.errors import AqtaError
from aqta.core.trading import OrderRequest


class BrokerError(AqtaError):
    code = "broker_error"
    http_status = 502


class BrokerOrderStatus(StrEnum):
    OPEN = "open"
    PARTIAL = "partial"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class BrokerAck:
    broker_order_id: str
    accepted: bool
    message: str = ""


@dataclass(frozen=True, slots=True)
class BrokerOrderSnapshot:
    broker_order_id: str
    status: BrokerOrderStatus
    filled_quantity: int = 0
    average_price: Decimal | None = None
    costs_inr: Decimal = Decimal(0)
    message: str = ""


@dataclass(frozen=True, slots=True)
class BrokerPosition:
    symbol: str
    exchange: str
    quantity: int
    average_price: Decimal


class BrokerPort(ABC):
    """All order traffic to a broker goes through an implementation of this class."""

    name: str
    is_live: bool

    @abstractmethod
    async def place_order(self, order: OrderRequest, algo_tag: str) -> BrokerAck: ...

    @abstractmethod
    async def get_order(self, broker_order_id: str) -> BrokerOrderSnapshot: ...

    @abstractmethod
    async def cancel_order(self, broker_order_id: str) -> bool: ...

    @abstractmethod
    async def modify_order(
        self, broker_order_id: str, *, limit_price: Decimal | None = None,
        quantity: int | None = None,
    ) -> bool: ...

    @abstractmethod
    async def positions(self) -> list[BrokerPosition]: ...


@dataclass(slots=True)
class ReconciliationReport:
    """FR-027: compare our orders/positions with the broker's every 60s and at end of day."""

    mismatches: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.mismatches


class Reconciler(Protocol):
    async def reconcile(self) -> ReconciliationReport: ...
