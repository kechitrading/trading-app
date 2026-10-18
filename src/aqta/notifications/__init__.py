"""Notifications: Telegram (allowlisted) with approval buttons and /kill, email stub, fakes,
600-char summaries.

BRD: BR-013, FR-023, FR-026, FR-044, FR-045, FR-052, NFR-006, NFR-017; WhatsApp pending Q-003.
"""

from aqta.notifications.bot import (
    ApprovalOutcome,
    BotActions,
    BotController,
    KillOutcome,
    ProposalCb,
    Reply,
    format_proposal,
    proposal_card,
)
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
    FakeProposalPublisher,
    TelegramNotifier,
    TelegramProposalPublisher,
    build_bot,
    build_dispatcher,
    build_notifier,
    build_publisher,
    is_allowed,
)

__all__ = [
    "MAX_SUMMARY_CHARS",
    "AllowlistMiddleware",
    "ApprovalOutcome",
    "BotActions",
    "BotController",
    "EmailNotifier",
    "FakeNotifier",
    "FakeProposalPublisher",
    "KillOutcome",
    "Level",
    "Notification",
    "NotifierPort",
    "ProposalCb",
    "Reply",
    "TelegramNotifier",
    "TelegramProposalPublisher",
    "TradeEvent",
    "TradeEventKind",
    "build_bot",
    "build_dispatcher",
    "build_notifier",
    "build_publisher",
    "format_proposal",
    "format_summary",
    "is_allowed",
    "proposal_card",
]
