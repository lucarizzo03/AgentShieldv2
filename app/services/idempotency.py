"""Idempotency slots for spend requests.

A key is claimed atomically *before* the engine runs, so two concurrent copies
of the same request cannot both evaluate and both execute. The slot holds an
``in_flight`` marker until the decision is cached under the same key; the marker
carries the transaction fingerprint so a key replayed with a different payload
is rejected instead of returning someone else's verdict.
"""
import json
from dataclasses import dataclass
from typing import Literal

from redis.asyncio import Redis

IN_FLIGHT_TTL_SECONDS = 120
COMPLETED_TTL_SECONDS = 24 * 60 * 60


@dataclass(slots=True)
class IdempotencyRecord:
    state: Literal["in_flight", "completed"]
    fingerprint: str | None
    response: dict | None


def _slot_key(agent_id: str, idempotency_key: str) -> str:
    return f"idempotency:{agent_id}:{idempotency_key}"


def _parse(raw: str) -> IdempotencyRecord:
    value = json.loads(raw)
    state = value.get("_state", "completed")
    return IdempotencyRecord(
        state="in_flight" if state == "in_flight" else "completed",
        fingerprint=value.get("_fingerprint"),
        response=None if state == "in_flight" else value,
    )


async def claim_idempotency_slot(
    redis: Redis,
    agent_id: str,
    idempotency_key: str | None,
    fingerprint: str,
) -> IdempotencyRecord | None:
    """Claim the slot for this key, or return the record already occupying it.

    ``None`` means the caller owns the slot and must evaluate the request.
    """
    if not idempotency_key:
        return None

    key = _slot_key(agent_id, idempotency_key)
    marker = json.dumps({"_state": "in_flight", "_fingerprint": fingerprint})
    claimed = await redis.set(key, marker, ex=IN_FLIGHT_TTL_SECONDS, nx=True)
    if claimed:
        return None

    existing = await redis.get(key)
    if not existing:
        # The slot expired between SET NX and GET; retry the claim once.
        claimed = await redis.set(key, marker, ex=IN_FLIGHT_TTL_SECONDS, nx=True)
        if claimed:
            return None
        existing = await redis.get(key)
        if not existing:
            return None
    return _parse(existing)


async def cache_idempotent_response(
    redis: Redis,
    agent_id: str,
    idempotency_key: str | None,
    payload: dict,
    fingerprint: str | None = None,
) -> None:
    if not idempotency_key:
        return
    record = {**payload, "_state": "completed", "_fingerprint": fingerprint}
    await redis.set(
        _slot_key(agent_id, idempotency_key),
        json.dumps(record, default=str),
        ex=COMPLETED_TTL_SECONDS,
    )


async def release_idempotency_slot(redis: Redis, agent_id: str, idempotency_key: str | None) -> None:
    """Drop an unfinished claim so a failed request can be retried immediately."""
    if not idempotency_key:
        return
    key = _slot_key(agent_id, idempotency_key)
    raw = await redis.get(key)
    if raw and _parse(raw).state == "in_flight":
        await redis.delete(key)
