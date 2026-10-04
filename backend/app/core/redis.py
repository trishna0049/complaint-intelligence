"""Shared async Redis client (cache, rate limits, pub/sub)."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from redis.asyncio import Redis

from app.core.config import get_settings

log = logging.getLogger(__name__)

_client: Redis | None = None


def get_redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(get_settings().redis_url, decode_responses=True, health_check_interval=30)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


# ------------------------------------------------------------------ cache
# Invalidation bumps a generation counter instead of scanning keys: old entries simply expire.
_GEN_KEY = "cache:gen:{ns}"


async def cached_json(ns: str, key: str, ttl: int, compute: Callable[[], Awaitable[Any]]) -> Any:
    r = get_redis()
    try:
        gen = await r.get(_GEN_KEY.format(ns=ns)) or "0"
        full = f"cache:{ns}:{gen}:{key}"
        hit = await r.get(full)
        if hit is not None:
            return json.loads(hit)
    except Exception as exc:  # Redis down: serve uncached rather than fail the request
        log.warning("cache read failed (%s); computing without cache", exc)
        return await compute()
    value = await compute()
    try:
        await r.set(full, json.dumps(value, default=str), ex=ttl)
    except Exception as exc:
        log.warning("cache write failed: %s", exc)
    return value


async def invalidate(ns: str) -> None:
    try:
        await get_redis().incr(_GEN_KEY.format(ns=ns))
    except Exception as exc:
        log.warning("cache invalidation failed: %s", exc)
