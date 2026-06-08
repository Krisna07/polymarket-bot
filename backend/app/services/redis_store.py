import json
from typing import Any

import redis.asyncio as aioredis
import structlog

from backend.app.config import get_settings

log = structlog.get_logger(__name__)

_redis: aioredis.Redis | None = None


def reset_redis_client() -> None:
    global _redis
    _redis = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(
            get_settings().redis_url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
    return _redis


async def redis_ping() -> bool:
    try:
        redis = await get_redis()
        await redis.ping()
        return True
    except Exception as e:
        log.warning("redis_ping_failed", error=str(e))
        reset_redis_client()
        return False


async def redis_get(key: str) -> str | None:
    try:
        return await (await get_redis()).get(key)
    except Exception as e:
        log.warning("redis_get_failed", key=key, error=str(e))
        reset_redis_client()
        return None


async def redis_set(key: str, value: str, ttl_sec: int | None = None) -> bool:
    try:
        redis = await get_redis()
        if ttl_sec:
            await redis.set(key, value, ex=ttl_sec)
        else:
            await redis.set(key, value)
        return True
    except Exception as e:
        log.warning("redis_set_failed", key=key, error=str(e))
        reset_redis_client()
        return False


async def redis_get_json(key: str) -> dict[str, Any] | None:
    raw = await redis_get(key)
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning("redis_get_json_failed", key=key, error=str(e))
        return None

    if not isinstance(value, dict):
        log.warning("redis_get_json_invalid_type", key=key, value_type=type(value).__name__)
        return None

    return value


async def redis_set_json(key: str, value: dict[str, Any], ttl_sec: int = 604_800) -> bool:
    return await redis_set(key, json.dumps(value), ttl_sec=ttl_sec)
