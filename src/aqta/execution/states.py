"""Order lifecycle state machine (FR-026): ack, partial fill, reject, cancel, modify, timeout."""

from __future__ import annotations

from enum import StrEnum

from aqta.core.errors import InvalidTransitionError


class OrderState(StrEnum):
    NEW = "new"
    PENDING_SUBMIT = "pending_submit"
    ACKNOWLEDGED = "acknowledged"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    MODIFY_PENDING = "modify_pending"
    CANCEL_PENDING = "cancel_pending"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"  # no ack in time: state unknown until reconciliation (FR-027)


class OrderEvent(StrEnum):
    SUBMIT = "submit"
    ACK = "ack"
    PARTIAL_FILL = "partial_fill"
    FILL = "fill"
    REJECT = "reject"
    MODIFY_REQUEST = "modify_request"
    MODIFY_CONFIRM = "modify_confirm"
    MODIFY_REJECT = "modify_reject"
    CANCEL_REQUEST = "cancel_request"
    CANCEL_CONFIRM = "cancel_confirm"
    TIMEOUT = "timeout"


S, E = OrderState, OrderEvent
TRANSITIONS: dict[OrderState, dict[OrderEvent, OrderState]] = {
    S.NEW: {E.SUBMIT: S.PENDING_SUBMIT, E.REJECT: S.REJECTED},
    S.PENDING_SUBMIT: {E.ACK: S.ACKNOWLEDGED, E.REJECT: S.REJECTED, E.TIMEOUT: S.TIMED_OUT},
    S.ACKNOWLEDGED: {
        E.PARTIAL_FILL: S.PARTIALLY_FILLED,
        E.FILL: S.FILLED,
        E.REJECT: S.REJECTED,
        E.CANCEL_REQUEST: S.CANCEL_PENDING,
        E.MODIFY_REQUEST: S.MODIFY_PENDING,
    },
    S.PARTIALLY_FILLED: {
        E.PARTIAL_FILL: S.PARTIALLY_FILLED,
        E.FILL: S.FILLED,
        E.CANCEL_REQUEST: S.CANCEL_PENDING,
        E.MODIFY_REQUEST: S.MODIFY_PENDING,
    },
    S.MODIFY_PENDING: {
        E.MODIFY_CONFIRM: S.ACKNOWLEDGED,
        E.MODIFY_REJECT: S.ACKNOWLEDGED,
        E.PARTIAL_FILL: S.PARTIALLY_FILLED,
        E.FILL: S.FILLED,
        E.CANCEL_REQUEST: S.CANCEL_PENDING,
    },
    S.CANCEL_PENDING: {
        E.CANCEL_CONFIRM: S.CANCELLED,
        E.PARTIAL_FILL: S.CANCEL_PENDING,
        E.FILL: S.FILLED,  # fill raced the cancel
    },
    S.TIMED_OUT: {
        E.ACK: S.ACKNOWLEDGED,  # late ack found by reconciliation
        E.REJECT: S.REJECTED,
        E.CANCEL_REQUEST: S.CANCEL_PENDING,
    },
    S.FILLED: {},
    S.CANCELLED: {},
    S.REJECTED: {},
}

TERMINAL = frozenset(state for state, moves in TRANSITIONS.items() if not moves)


def next_state(state: OrderState, event: OrderEvent) -> OrderState:
    try:
        return TRANSITIONS[state][event]
    except KeyError:
        raise InvalidTransitionError(f"order: {event} not allowed in state {state}") from None


def is_open(state: OrderState) -> bool:
    return state not in TERMINAL and state is not OrderState.NEW
