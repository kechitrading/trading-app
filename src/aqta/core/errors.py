"""Error hierarchy. API error handlers map these to HTTP responses."""

from __future__ import annotations


class AqtaError(Exception):
    """Base class for all domain errors."""

    code: str = "aqta_error"
    http_status: int = 400


class ConfigError(AqtaError, ValueError):
    code = "config_error"
    http_status = 500


class LiveTradingNotEnabledError(ConfigError):
    code = "live_trading_not_enabled"


class NotFoundError(AqtaError):
    code = "not_found"
    http_status = 404


class AuthError(AqtaError):
    code = "unauthorized"
    http_status = 401


class InvalidTransitionError(AqtaError):
    code = "invalid_transition"
    http_status = 409


class SafetyViolationError(AqtaError):
    """Raised when code tries to cross a safety boundary (e.g. live adapter in paper mode)."""

    code = "safety_violation"
    http_status = 403
