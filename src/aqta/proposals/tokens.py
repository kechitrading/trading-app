"""Signed, expiring, single-use approval tokens bound to the exact order (RULE-001, FR-024).

Format: ``v1.<base64url(claims-json)>.<base64url(hmac-sha256)>``. The claims carry the SHA-256
of the order's canonical JSON, so any change to the order after approval invalidates the token.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

from aqta.core.clock import Clock
from aqta.core.errors import AqtaError, ConfigError
from aqta.core.ids import new_nonce
from aqta.core.trading import OrderRequest

TOKEN_VERSION = "v1"  # noqa: S105 - format version, not a secret
MAX_CLOCK_SKEW = timedelta(seconds=5)
MIN_SECRET_BYTES = 16


class TokenFailure(StrEnum):
    MISSING = "missing"
    MALFORMED = "malformed"
    BAD_SIGNATURE = "bad_signature"
    EXPIRED = "expired"
    NOT_YET_VALID = "not_yet_valid"
    ORDER_MISMATCH = "order_mismatch"
    REPLAYED = "replayed"


class ApprovalTokenError(AqtaError):
    code = "approval_invalid"
    http_status = 403

    def __init__(self, failure: TokenFailure, detail: str = "") -> None:
        self.failure = failure
        super().__init__(
            f"approval token rejected: {failure.value}{': ' + detail if detail else ''}"
        )


@dataclass(frozen=True, slots=True)
class ApprovalClaims:
    proposal_id: str
    client_order_id: str
    order_hash: str
    actor: str
    nonce: str
    issued_at: datetime
    expires_at: datetime

    def to_json(self) -> dict[str, Any]:
        return {
            "pid": self.proposal_id,
            "coid": self.client_order_id,
            "oh": self.order_hash,
            "act": self.actor,
            "n": self.nonce,
            "iat": self.issued_at.isoformat(),
            "exp": self.expires_at.isoformat(),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ApprovalClaims:
        return cls(
            proposal_id=str(data["pid"]),
            client_order_id=str(data["coid"]),
            order_hash=str(data["oh"]),
            actor=str(data["act"]),
            nonce=str(data["n"]),
            issued_at=datetime.fromisoformat(data["iat"]),
            expires_at=datetime.fromisoformat(data["exp"]),
        )


class NonceStore(Protocol):
    async def consume(self, nonce: str, expires_at: datetime) -> bool:
        """Mark ``nonce`` used. Returns False if it was already used (replay)."""
        ...


class InMemoryNonceStore:
    def __init__(self) -> None:
        self._used: dict[str, datetime] = {}

    async def consume(self, nonce: str, expires_at: datetime) -> bool:
        if nonce in self._used:
            return False
        self._used[nonce] = expires_at
        return True


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


class ApprovalTokenService:
    def __init__(
        self, secret: str, clock: Clock, nonces: NonceStore, default_ttl_seconds: int = 300
    ) -> None:
        if len(secret.encode()) < MIN_SECRET_BYTES:
            raise ConfigError("APPROVAL_SECRET is missing or too short")
        self._key = secret.encode()
        self._clock = clock
        self._nonces = nonces
        self._ttl = timedelta(seconds=default_ttl_seconds)

    def _sign(self, body: str) -> str:
        return _b64(hmac.new(self._key, body.encode("ascii"), hashlib.sha256).digest())

    def issue(self, order: OrderRequest, actor: str, ttl_seconds: int | None = None) -> str:
        now = self._clock.now()
        ttl = timedelta(seconds=ttl_seconds) if ttl_seconds is not None else self._ttl
        claims = ApprovalClaims(
            proposal_id=order.proposal_id,
            client_order_id=order.client_order_id,
            order_hash=order.payload_hash(),
            actor=actor,
            nonce=new_nonce(),
            issued_at=now,
            expires_at=now + ttl,
        )
        body = f"{TOKEN_VERSION}.{_b64(json.dumps(claims.to_json(), sort_keys=True).encode())}"
        return f"{body}.{self._sign(body)}"

    def verify(self, token: str | None, order: OrderRequest) -> ApprovalClaims:
        """Check signature, validity window and order binding. Does not consume the nonce."""
        if not token:
            raise ApprovalTokenError(TokenFailure.MISSING)
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != TOKEN_VERSION:
            raise ApprovalTokenError(TokenFailure.MALFORMED)
        body = f"{parts[0]}.{parts[1]}"
        if not hmac.compare_digest(self._sign(body), parts[2]):
            raise ApprovalTokenError(TokenFailure.BAD_SIGNATURE)
        try:
            claims = ApprovalClaims.from_json(json.loads(_unb64(parts[1])))
        except (ValueError, KeyError, TypeError) as exc:
            raise ApprovalTokenError(TokenFailure.MALFORMED) from exc

        now = self._clock.now()
        if now >= claims.expires_at:
            raise ApprovalTokenError(TokenFailure.EXPIRED, f"expired at {claims.expires_at}")
        if claims.issued_at - now > MAX_CLOCK_SKEW:
            raise ApprovalTokenError(TokenFailure.NOT_YET_VALID)
        if not hmac.compare_digest(claims.order_hash, order.payload_hash()):
            raise ApprovalTokenError(TokenFailure.ORDER_MISMATCH, "order differs from approval")
        return claims

    async def verify_and_consume(self, token: str | None, order: OrderRequest) -> ApprovalClaims:
        claims = self.verify(token, order)
        if not await self._nonces.consume(claims.nonce, claims.expires_at):
            raise ApprovalTokenError(TokenFailure.REPLAYED, "token already used")
        return claims
