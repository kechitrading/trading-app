"""structlog JSON logging with a secret-redaction processor (NFR-008)."""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog
from pydantic import SecretStr

REDACTED = "***REDACTED***"
_SENSITIVE_KEY = re.compile(
    r"(pass(word)?|secret|token|api[_-]?key|authorization|auth|credential|private[_-]?key|totp|otp)",
    re.IGNORECASE,
)
# Value patterns that look like credentials even under innocent keys.
_SENSITIVE_VALUE = re.compile(
    r"(Bearer\s+[A-Za-z0-9._\-]+|\b\d{8,12}:[A-Za-z0-9_\-]{30,}\b|"
    r"(postgres(ql)?(\+\w+)?|redis)://[^:/\s]+:[^@\s]+@)",
)


def _redact_value(value: Any) -> Any:
    if isinstance(value, SecretStr):
        return REDACTED
    if isinstance(value, str):
        return _SENSITIVE_VALUE.sub(REDACTED, value)
    if isinstance(value, Mapping):
        return {k: (REDACTED if _is_sensitive(k) else _redact_value(v)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return type(value)(_redact_value(v) for v in value)
    return value


def _is_sensitive(key: object) -> bool:
    return isinstance(key, str) and bool(_SENSITIVE_KEY.search(key))


def redact_secrets(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor: mask sensitive keys and credential-looking values."""
    for key in list(event_dict.keys()):
        if _is_sensitive(key):
            event_dict[key] = REDACTED
        else:
            event_dict[key] = _redact_value(event_dict[key])
    return event_dict


def configure_logging(level: str = "INFO", *, json: bool = True) -> None:
    renderer: Any = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            redact_secrets,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> Any:
    return structlog.get_logger(name)
