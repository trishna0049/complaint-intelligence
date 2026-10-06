"""Shared async Redis client (cache, rate limits, pub/sub)."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.engine import make_url

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
# Keys are prefixed with the database name, so two databases sharing one Redis (dev and e2e) never mix.


def _db_tag() -> str:
    return make_url(get_settings().database_url).database or "db"


def _gen_key(ns: str) -> str:
    return f"cache:{_db_tag()}:gen:{ns}"


async def cached_json(ns: str, key: str, ttl: int, compute: Callable[[], Awaitable[Any]]) -> Any:
    r = get_redis()
    try:
        gen = await r.get(_gen_key(ns)) or "0"
        full = f"cache:{_db_tag()}:{ns}:{gen}:{key}"
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
        await get_redis().incr(_gen_key(ns))
    except Exception as exc:
        log.warning("cache invalidation failed: %s", exc)


# ------------------------------------------------------------------ pub/sub
def channel(name: str) -> str:
    """A pub/sub channel name, namespaced by database like the cache keys (dev and e2e never cross)."""
    return f"pubsub:{_db_tag()}:{name}"
