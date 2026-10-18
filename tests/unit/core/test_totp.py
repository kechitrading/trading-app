from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from aqta.core.clock import FrozenClock
from aqta.core.errors import ConfigError
from aqta.core.totp import (
    STEP_SECONDS,
    TotpVerifier,
    decode_secret,
    generate_secret,
    hotp,
    provisioning_uri,
)

# RFC 6238 appendix B, SHA-1 seed.
RFC_KEY = b"12345678901234567890"
RFC_SECRET = base64.b32encode(RFC_KEY).decode()


@pytest.mark.parametrize(
    ("unix_time", "expected"),
    [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
    ],
)
def test_rfc6238_vectors(unix_time: int, expected: str) -> None:
    assert hotp(RFC_KEY, unix_time // STEP_SECONDS, digits=8) == expected


def _at(unix_time: int) -> FrozenClock:
    return FrozenClock(datetime.fromtimestamp(unix_time, tz=UTC))


def _code(unix_time: int) -> str:
    return hotp(RFC_KEY, unix_time // STEP_SECONDS)


def test_accepts_current_code_once() -> None:
    v = TotpVerifier(RFC_SECRET, _at(1_700_000_000))
    code = _code(1_700_000_000)
    assert v.verify(code)
    assert not v.verify(code)  # replay


def test_allows_one_step_of_drift_but_not_two() -> None:
    now = 1_700_000_010
    assert TotpVerifier(RFC_SECRET, _at(now)).verify(_code(now - STEP_SECONDS))
    assert TotpVerifier(RFC_SECRET, _at(now)).verify(_code(now + STEP_SECONDS))
    assert not TotpVerifier(RFC_SECRET, _at(now)).verify(_code(now - 2 * STEP_SECONDS))
    assert not TotpVerifier(RFC_SECRET, _at(now)).verify(_code(now + 2 * STEP_SECONDS))


def test_older_code_rejected_after_newer_one_used() -> None:
    now = 1_700_000_010
    v = TotpVerifier(RFC_SECRET, _at(now))
    assert v.verify(_code(now))
    assert not v.verify(_code(now - STEP_SECONDS))


def test_next_step_code_works_after_time_moves() -> None:
    clock = _at(1_700_000_010)
    v = TotpVerifier(RFC_SECRET, clock)
    assert v.verify(_code(1_700_000_010))
    clock.advance(timedelta(seconds=STEP_SECONDS))
    assert v.verify(_code(1_700_000_010 + STEP_SECONDS))


@pytest.mark.parametrize("bad", [None, "", "12345", "1234567", "abcdef", "12 34 5x"])
def test_malformed_codes_rejected(bad: str | None) -> None:
    assert not TotpVerifier(RFC_SECRET, _at(1_700_000_000)).verify(bad)


def test_code_with_spaces_accepted() -> None:
    code = _code(1_700_000_000)
    assert TotpVerifier(RFC_SECRET, _at(1_700_000_000)).verify(f"{code[:3]} {code[3:]}")


def test_generated_secret_round_trips_and_is_long_enough() -> None:
    secret = generate_secret()
    assert len(decode_secret(secret)) == 20
    assert decode_secret(secret.lower()) == decode_secret(secret)
    assert generate_secret() != secret


@pytest.mark.parametrize("bad", ["not base32 !!", "JBSWY3DP"])
def test_bad_secrets_rejected(bad: str) -> None:
    with pytest.raises(ConfigError):
        decode_secret(bad)


def test_provisioning_uri() -> None:
    uri = urlparse(provisioning_uri(RFC_SECRET))
    assert uri.scheme == "otpauth" and uri.netloc == "totp"
    assert uri.path == "/AQTA%3Akashyap"
    query = parse_qs(uri.query)
    assert query["secret"] == [RFC_SECRET] and query["issuer"] == ["AQTA"]
    assert query["digits"] == ["6"] and query["period"] == ["30"]
