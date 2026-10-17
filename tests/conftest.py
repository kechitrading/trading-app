from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr

from aqta.core.clock import FrozenClock
from aqta.core.settings import Settings

TEST_API_TOKEN = "test-api-token-0123456789abcdef"
TEST_APPROVAL_SECRET = "test-approval-secret-0123456789abcdef-xyz"


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let a developer's real environment leak into tests."""
    for key in list(os.environ):
        if key.startswith(("TRADING_", "LIVE_", "RISK__", "ASTROLOGY__", "TELEGRAM_", "APPROVAL_")):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        app_env="test",
        api_token=SecretStr(TEST_API_TOKEN),
        approval_secret=SecretStr(TEST_APPROVAL_SECRET),
    )


@pytest.fixture
def clock() -> FrozenClock:
    # Tuesday 2026-10-20 10:00 IST == 04:30 UTC, inside NSE hours.
    return FrozenClock(datetime(2026, 10, 20, 4, 30, tzinfo=UTC))
