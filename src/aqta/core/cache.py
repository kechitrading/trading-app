"""Redis client factory (cache, pub/sub, Arq job queue backend, kill-switch fast path)."""

from __future__ import annotations

from typing import Any

from redis.asyncio import Redis


def create_redis(redis_url: str) -> Redis:
    return Redis.from_url(redis_url, decode_responses=True)


async def ping_redis(client: Any) -> bool:
    return bool(await client.ping())
