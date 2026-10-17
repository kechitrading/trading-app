from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

import pytest
import structlog
from pydantic import SecretStr

from aqta.core.hashing import canonical_json, sha256_canonical, to_jsonable
from aqta.core.ids import new_id, new_nonce
from aqta.core.logs import REDACTED, configure_logging, get_logger, redact_secrets


def test_redaction_masks_sensitive_keys_and_values() -> None:
    event = {
        "event": "login",
        "api_token": "abc",
        "Authorization": "Bearer xyz",
        "password": "p",
        "nested": {"approval_secret": "s", "ok": 1},
        "header": "Bearer eyJhbGciOi.payload.sig",
        "dsn": "postgresql+asyncpg://aqta:hunter2@db:5432/aqta",
        "bot": "123456789:AAEhBOweik6ad9r_QXMENQjcrGbqCr4K-ra",
        "wrapped": SecretStr("hidden"),
        "items": ["Bearer abc.def", 3],
    }
    out = redact_secrets(None, "info", dict(event))
    assert out["api_token"] == REDACTED
    assert out["Authorization"] == REDACTED
    assert out["password"] == REDACTED
    assert out["nested"] == {"approval_secret": REDACTED, "ok": 1}
    assert "eyJ" not in out["header"]
    assert "hunter2" not in out["dsn"]
    assert "AAEh" not in out["bot"]
    assert out["wrapped"] == REDACTED
    assert out["items"][0] == REDACTED and out["items"][1] == 3
    assert out["event"] == "login"


def test_configured_logger_emits_redacted_json(capsys: pytest.CaptureFixture[str]) -> None:
    structlog.reset_defaults()
    configure_logging("INFO", json=True)
    get_logger("t").info("hello", api_key="k-123", value=5)
    line = capsys.readouterr().out.strip().splitlines()[-1]
    data = json.loads(line)
    assert data["api_key"] == REDACTED
    assert data["value"] == 5
    assert data["timestamp"].endswith("Z")
    structlog.reset_defaults()


class _Color(Enum):
    RED = "red"


def test_canonical_json_is_deterministic() -> None:
    a = {"b": Decimal("1.50"), "a": [datetime(2026, 1, 1, tzinfo=UTC), _Color.RED]}
    b = {"a": [datetime(2026, 1, 1, tzinfo=UTC), _Color.RED], "b": Decimal("1.50")}
    assert canonical_json(a) == canonical_json(b)
    assert sha256_canonical(a) == sha256_canonical(b)
    assert len(sha256_canonical(a)) == 64
    assert to_jsonable({1: {3, 1, 2}}) == {"1": [1, 2, 3]}
    assert to_jsonable(UUID(int=1)) == "00000000-0000-0000-0000-000000000001"


def test_ids() -> None:
    assert new_id("ord").startswith("ord_")
    assert len(new_id()) == 32
    assert new_nonce() != new_nonce()
