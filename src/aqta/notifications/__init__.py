"""Notifications: Telegram (allowlisted), email stub, fake notifier, 600-char summaries.

BRD: BR-013, FR-023, FR-026, FR-044, FR-045, FR-052, NFR-006, NFR-017; WhatsApp pending Q-003.
"""

from aqta.notifications.formatter import (
    MAX_SUMMARY_CHARS,
    TradeEvent,
    TradeEventKind,
    format_summary,
)
from aqta.notifications.ports import (
    EmailNotifier,
    FakeNotifier,
    Level,
    Notification,
    NotifierPort,
)
from aqta.notifications.telegram import (
    AllowlistMiddleware,
    TelegramNotifier,
    build_dispatcher,
    build_notifier,
    is_allowed,
)

__all__ = [
    "MAX_SUMMARY_CHARS",
    "AllowlistMiddleware",
    "EmailNotifier",
    "FakeNotifier",
    "Level",
    "Notification",
    "NotifierPort",
    "TelegramNotifier",
    "TradeEvent",
    "TradeEventKind",
    "build_dispatcher",
    "build_notifier",
    "format_summary",
    "is_allowed",
]
