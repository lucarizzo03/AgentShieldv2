import json

from redis.asyncio import Redis


async def read_cached_idempotent_response(
    redis: Redis,
    agent_id: str,
    idempotency_key: str | None,
) -> dict | None:
    if not idempotency_key:
        return None
    key = f"idempotency:{agent_id}:{idempotency_key}"
    value = await redis.get(key)
    if not value:
        return None
    return json.loads(value)


async def cache_idempotent_response(
    redis: Redis,
    agent_id: str,
    idempotency_key: str | None,
    payload: dict,
) -> None:
    if not idempotency_key:
        return
    key = f"idempotency:{agent_id}:{idempotency_key}"
    await redis.set(key, json.dumps(payload, default=str), ex=24 * 60 * 60)

