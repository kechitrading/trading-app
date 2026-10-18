"""Time-based one-time passwords, RFC 6238 (NFR-009, FR-052).

Standard library only, so any authenticator app (Google Authenticator, Authy, 1Password) works with
the base32 secret from ``scripts/mfa_setup.py``. Codes are SHA-1, 6 digits, 30-second steps.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import struct
from urllib.parse import quote

from aqta.core.clock import Clock
from aqta.core.errors import ConfigError

STEP_SECONDS = 30
DIGITS = 6
MIN_SECRET_BYTES = 16  # RFC 4226 minimum is 128 bits


def generate_secret() -> str:
    """A new random 160-bit secret, base32 without padding (what authenticator apps expect)."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def decode_secret(secret_b32: str) -> bytes:
    """Decode a base32 secret, tolerating spaces, lower case and missing padding."""
    cleaned = secret_b32.replace(" ", "").upper()
    try:
        key = base64.b32decode(cleaned + "=" * (-len(cleaned) % 8))
    except (binascii.Error, ValueError) as exc:
        raise ConfigError("MFA_TOTP_SECRET is not valid base32") from exc
    if len(key) < MIN_SECRET_BYTES:
        raise ConfigError(f"MFA_TOTP_SECRET must be at least {MIN_SECRET_BYTES} bytes")
    return key


def hotp(key: bytes, counter: int, digits: int = DIGITS) -> str:
    """RFC 4226 HOTP value for ``counter``."""
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**digits).zfill(digits)


def provisioning_uri(secret_b32: str, account: str = "kashyap", issuer: str = "AQTA") -> str:
    """``otpauth://`` URI that authenticator apps import (or render as a QR code)."""
    label = quote(f"{issuer}:{account}")
    query = f"secret={secret_b32}&issuer={quote(issuer)}&digits={DIGITS}&period={STEP_SECONDS}"
    return f"otpauth://totp/{label}?{query}"


class TotpVerifier:
    """Checks codes against the clock, allowing ``window`` steps of drift either way.

    A code is accepted at most once: after a code for step N is used, codes for step N and
    earlier are rejected (replay protection). The state is per process; the API runs one.
    """

    def __init__(self, secret_b32: str, clock: Clock, window: int = 1) -> None:
        self._key = decode_secret(secret_b32)
        self._clock = clock
        self._window = window
        self._last_counter = -1

    def verify(self, code: str | None) -> bool:
        if code is None:
            return False
        code = code.strip().replace(" ", "")
        if len(code) != DIGITS or not code.isdigit():
            return False
        now = int(self._clock.now().timestamp()) // STEP_SECONDS
        for counter in range(now - self._window, now + self._window + 1):
            if counter <= self._last_counter:
                continue
            if hmac.compare_digest(hotp(self._key, counter), code):
                self._last_counter = counter
                return True
        return False
