"""Notifier port and simple adapters (FR-023, FR-026, FR-044, FR-045)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from aqta.core.logs import get_logger

log = get_logger(__name__)


class Level(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class Notification:
    text: str
    level: Level = Level.INFO
    kind: str = "message"


class NotifierPort(Protocol):
    async def send(self, notification: Notification) -> None: ...


class FakeNotifier:
    """Dev/test notifier: records and logs messages. Used whenever no Telegram token is set."""

    def __init__(self) -> None:
        self.sent: list[Notification] = []

    async def send(self, notification: Notification) -> None:
        self.sent.append(notification)
        log.info("notify.fake", kind=notification.kind, level=notification.level,
                 text=notification.text)


class EmailNotifier:
    """TODO(FR-045, DEP-003): SMTP/SES delivery of PDF/Word reports."""

    async def send(self, notification: Notification) -> None:
        raise NotImplementedError("Email delivery is not implemented yet (FR-045)")
