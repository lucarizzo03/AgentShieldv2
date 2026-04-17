from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

from redis.asyncio import Redis

from app.core.config import get_settings

settings = get_settings()
redis_client = Redis.from_url(settings.redis_dsn, decode_responses=True)


def seconds_until_next_utc_midnight(buffer_seconds: int = 60) -> int:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((tomorrow - now).total_seconds()) + buffer_seconds


async def get_redis() -> Redis:
    return redis_client


async def with_redis_lock(
    redis: Redis,
    key: str,
    ttl_seconds: int,
    callback: Callable[[], Awaitable[dict]],
) -> dict:
    lock_key = f"lock:{key}"
    acquired = await redis.set(lock_key, "1", ex=ttl_seconds, nx=True)
    if not acquired:
        return {"locked": True}
    try:
        return await callback()
    finally:
        await redis.delete(lock_key)

