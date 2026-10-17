"""Redis-backed nonce store: SET NX with expiry makes every approval token single-use."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

NONCE_PREFIX = "aqta:approval:nonce:"


class RedisNonceStore:
    def __init__(self, redis: Any) -> None:
        self._redis = redis

    async def consume(self, nonce: str, expires_at: datetime) -> bool:
        ttl = max(1, math.ceil((expires_at - datetime.now(UTC)).total_seconds()) + 60)
        return bool(await self._redis.set(f"{NONCE_PREFIX}{nonce}", "1", nx=True, ex=ttl))
