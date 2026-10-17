"""LLM port and monthly cost tracker (FR-053, CON-002, NFR-014, Q-010).

The provider is still to be chosen (Q-010); nothing here calls an API.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel

from aqta.core.settings import BudgetSettings


class LLMResponse(BaseModel):
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_inr: Decimal


class LLMPort(Protocol):
    async def complete(self, prompt: str, *, max_tokens: int = 1024) -> LLMResponse: ...


class BudgetAlert(BaseModel):
    budget: str  # "ai" | "data"
    threshold_pct: int
    spent_inr: Decimal
    cap_inr: Decimal
    month: str


class CostTracker:
    """Tracks spend per calendar month and raises each threshold alert once (80% and 100%)."""

    def __init__(
        self, budget: str, cap_inr: Decimal, thresholds: Sequence[int] = (80, 100)
    ) -> None:
        self._budget = budget
        self._cap = cap_inr
        self._thresholds = sorted(thresholds)
        self._spent: dict[str, Decimal] = {}
        self._alerted: set[tuple[str, int]] = set()

    @classmethod
    def for_ai(cls, budget: BudgetSettings) -> CostTracker:
        return cls("ai", budget.ai_monthly_inr, budget.alert_thresholds_pct)

    @classmethod
    def for_data(cls, budget: BudgetSettings) -> CostTracker:
        return cls("data", budget.data_monthly_inr, budget.alert_thresholds_pct)

    def spent(self, day: date) -> Decimal:
        return self._spent.get(day.strftime("%Y-%m"), Decimal(0))

    def record(self, day: date, cost_inr: Decimal) -> list[BudgetAlert]:
        month = day.strftime("%Y-%m")
        total = self._spent.get(month, Decimal(0)) + cost_inr
        self._spent[month] = total
        alerts: list[BudgetAlert] = []
        for pct in self._thresholds:
            if total >= self._cap * pct / 100 and (month, pct) not in self._alerted:
                self._alerted.add((month, pct))
                alerts.append(
                    BudgetAlert(
                        budget=self._budget,
                        threshold_pct=pct,
                        spent_inr=total,
                        cap_inr=self._cap,
                        month=month,
                    )
                )
        return alerts

    def over_budget(self, day: date) -> bool:
        return self.spent(day) >= self._cap


__all__ = ["BudgetAlert", "CostTracker", "LLMPort", "LLMResponse"]
