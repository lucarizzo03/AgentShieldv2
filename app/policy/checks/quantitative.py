import hashlib
import json
from datetime import datetime, timezone

from redis.asyncio import Redis

from app.core.config import get_settings
from app.db.redis import seconds_until_next_utc_midnight
from app.models.agent import Agent
from app.policy.currency import to_major_units
from app.policy.verdicts import CheckResult

RESERVATION_MARKER_PREFIX = "budget:reserved:"
# Placeholder for the Lua scripts' marker slot on paths that keep no marker.
# It is never written, so the reconciler never sees it.
_NO_MARKER_KEY = f"{RESERVATION_MARKER_PREFIX}__none__"

# Atomically INCR and set TTL only on first creation, avoiding the
# INCR-then-conditional-EXPIRE race where concurrent requests both
# skip count==1 and leave keys with no TTL.
_INCR_WITH_TTL = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""

# Atomically checks the daily budget limit and reserves (increments) the
# amount only if the projected total stays within the limit.  This closes
# the TOCTOU race where two concurrent requests both pass a non-atomic
# GET → compare → INCRBY sequence.
#
# A reservation marker (KEYS[2]) is written in the same call so an outstanding
# reservation is discoverable: without it, a crash between reserve and rollback
# consumes daily budget with nothing on record to reconcile against.  Pass a
# marker TTL of 0 to skip the marker (the HITL commit path, which is terminal).
#
# Returns a 3-element array: {reserved, current_before, projected}
#   reserved == 1  → within budget, amount has been incremented (reserved)
#   reserved == 0  → over budget, Redis state is unchanged
_CHECK_AND_RESERVE_BUDGET = """
local current = tonumber(redis.call('GET', KEYS[1])) or 0
local projected = current + tonumber(ARGV[1])
if projected > tonumber(ARGV[2]) then
    return {0, current, projected}
end
redis.call('INCRBY', KEYS[1], ARGV[1])
local ttl = redis.call('TTL', KEYS[1])
if ttl == -1 or ttl == -2 then
    redis.call('EXPIRE', KEYS[1], ARGV[3])
end
if tonumber(ARGV[5]) > 0 then
    redis.call('SET', KEYS[2], ARGV[4], 'EX', ARGV[5])
end
return {1, current, projected}
"""

# Releases a tentative reservation on the exact key it was taken against.
# A bare DECRBY would (a) recreate the key with a negative value and no TTL if
# it had already expired, and (b) drive the counter below zero, handing the
# agent extra budget.  This only touches a key that still exists and floors at 0.
#
# The marker (KEYS[2]) is cleared in the same call so the reconciler cannot
# release the same reservation a second time.
_RELEASE_BUDGET_RESERVATION = """
redis.call('DEL', KEYS[2])
if redis.call('EXISTS', KEYS[1]) == 0 then
    return 0
end
local remaining = redis.call('DECRBY', KEYS[1], ARGV[1])
if remaining < 0 then
    redis.call('SET', KEYS[1], 0, 'KEEPTTL')
end
return 1
"""

# Decrements a velocity counter without resurrecting an expired window or
# driving the count below zero.
_RELEASE_VELOCITY_COUNTER = """
if redis.call('EXISTS', KEYS[1]) == 0 then
    return 0
end
local remaining = redis.call('DECR', KEYS[1])
if remaining <= 0 then
    redis.call('DEL', KEYS[1])
end
return 1
"""


def daily_budget_key(
    agent_id: str,
    asset_type: str,
    moment: datetime | None = None,
    currency: str = "USD",
) -> str:
    """Scoped by currency as well as asset type: one counter per currency keeps
    unlike amounts from summing into a limit denominated in a single one."""
    date_key = (moment or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    return f"budget:daily:{agent_id}:{asset_type}:{currency.strip().upper()}:{date_key}"


def reservation_marker_key(reservation_id: str) -> str:
    return f"{RESERVATION_MARKER_PREFIX}{reservation_id}"


def transaction_fingerprint(
    vendor: str,
    amount_cents: int,
    item_description: str,
    asset_type: str,
    stablecoin_symbol: str | None,
    network: str | None,
    destination_address: str | None,
) -> str:
    payload = "|".join(
        [
            vendor.strip().lower(),
            str(amount_cents),
            item_description.strip().lower(),
            asset_type,
            stablecoin_symbol or "",
            network or "",
            (destination_address or "").strip().lower(),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def velocity_fingerprint(
    vendor: str,
    asset_type: str,
    stablecoin_symbol: str | None,
    network: str | None,
    destination_address: str | None,
) -> str:
    """Fingerprint for the loop check.  Deliberately excludes the amount and the
    item description: an agent stuck in a retry loop typically varies both, and
    an amount-bound fingerprint means a one-cent difference produces a fresh key
    and the loop check never trips.  Idempotency keeps using
    ``transaction_fingerprint``, which must stay amount-bound."""
    payload = "|".join(
        [
            vendor.strip().lower(),
            asset_type,
            stablecoin_symbol or "",
            network or "",
            (destination_address or "").strip().lower(),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def run_quantitative_checks(
    redis: Redis,
    agent: Agent,
    amount_cents: int,
    asset_type: str,
    network: str | None,
    destination_address: str | None,
    fingerprint: str,
    reservation_id: str | None = None,
) -> CheckResult:
    settings = get_settings()
    check = CheckResult()

    budget_key = daily_budget_key(agent.agent_id, asset_type, currency=agent.currency)
    loop_key = f"loop:txn:{agent.agent_id}:{fingerprint}"
    burst_key = (
        f"dest:burst:{agent.agent_id}:{network}:{destination_address}"
        if network and destination_address
        else None
    )

    ttl = seconds_until_next_utc_midnight()
    marker_key = reservation_marker_key(reservation_id) if reservation_id else _NO_MARKER_KEY
    marker_ttl = settings.budget_reservation_marker_ttl_seconds if reservation_id else 0
    marker_value = json.dumps(
        {
            "budget_key": budget_key,
            "amount_cents": amount_cents,
            "agent_id": agent.agent_id,
            "reserved_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    result = await redis.eval(
        _CHECK_AND_RESERVE_BUDGET, 2, budget_key, marker_key,
        amount_cents, agent.daily_budget_limit_cents, ttl, marker_value, marker_ttl,
    )
    reserved = bool(int(result[0]))
    current_spent = int(result[1])
    projected = int(result[2])
    budget_exceeded = not reserved
    if budget_exceeded:
        check.hard_deny = True
        check.reasons.append("BUDGET_DAILY_LIMIT_EXCEEDED")
    else:
        check.reasons.append("BUDGET_WITHIN_LIMIT")

    loop_count = 0
    destination_burst = 0

    if not budget_exceeded:
        # `>=` means the threshold-th identical request within the window is the
        # one that trips: with loop_threshold=5, the 5th request is denied.
        loop_count = await redis.eval(_INCR_WITH_TTL, 1, loop_key, settings.loop_window_seconds)
        if loop_count >= settings.loop_threshold:
            check.hard_deny = True
            check.reasons.append("LOOP_PATTERN_DETECTED")
        else:
            check.reasons.append("NO_LOOP_PATTERN")

        if burst_key:
            destination_burst = await redis.eval(_INCR_WITH_TTL, 1, burst_key, settings.loop_window_seconds)
            if destination_burst >= settings.loop_threshold:
                check.hard_deny = True
                check.reasons.append("DESTINATION_BURST_DETECTED")

    check.context = {
        "budget_key": budget_key,
        "reservation_marker_key": marker_key if marker_ttl else None,
        "loop_key": loop_key if not budget_exceeded else None,
        "burst_key": burst_key if burst_key and not budget_exceeded else None,
        "currency": agent.currency,
        "daily_spent": to_major_units(current_spent, agent.currency),
        "projected_spent": to_major_units(projected, agent.currency),
        "budget_exceeded": budget_exceeded,
        "budget_reserved": reserved,
        "loop_count": int(loop_count),
        "destination_burst_count": int(destination_burst),
    }
    return check


async def commit_budget_spend(
    redis: Redis,
    agent_id: str,
    asset_type: str,
    amount_cents: int,
    daily_budget_limit_cents: int,
    currency: str = "USD",
) -> tuple[bool, int]:
    """Full budget commit, used by the HITL APPROVE path where the earlier
    tentative reservation was rolled back before the human decision.

    The limit is re-checked atomically: an approval that arrives hours later
    must not push the agent past the budget it has spent in the meantime.
    Returns ``(committed, spend_before)``."""
    budget_key = daily_budget_key(agent_id, asset_type, currency=currency)
    result = await redis.eval(
        _CHECK_AND_RESERVE_BUDGET, 2, budget_key, _NO_MARKER_KEY,
        amount_cents, daily_budget_limit_cents, seconds_until_next_utc_midnight(), "", 0,
    )
    return bool(int(result[0])), int(result[1])


async def finalize_budget_reservation(redis: Redis, budget_key: str) -> None:
    """Finalizes a tentative reservation made during the budget check by refreshing
    the TTL.  The INCRBY already happened atomically in _CHECK_AND_RESERVE_BUDGET,
    so this only needs to keep the key alive until midnight."""
    await redis.expire(budget_key, seconds_until_next_utc_midnight())


async def rollback_budget_reservation(
    redis: Redis,
    budget_key: str,
    amount_cents: int,
    marker_key: str | None = None,
) -> None:
    """Rolls back the tentative budget reservation when a spend is denied
    (MALICIOUS verdict) or put on hold (SUSPICIOUS / HITL).  For HITL, the
    amount is re-committed via commit_budget_spend only after human approval.

    ``budget_key`` must be the key the reservation was taken against, not a key
    recomputed from the current time: a rollback that crosses UTC midnight would
    otherwise decrement the next day's counter."""
    await redis.eval(
        _RELEASE_BUDGET_RESERVATION, 2, budget_key, marker_key or _NO_MARKER_KEY,
        amount_cents,
    )


async def clear_reservation_marker(redis: Redis, marker_key: str | None) -> None:
    """Drops the outstanding-reservation marker once the reservation has reached
    a terminal state, so the reconciler leaves it alone."""
    if marker_key:
        await redis.delete(marker_key)


async def release_velocity_counters(
    redis: Redis,
    loop_key: str | None,
    burst_key: str | None,
) -> None:
    """Gives back the loop and destination-burst increments taken by a request
    that never executed.  Without this, a run of blocked attempts consumes the
    window for the legitimate traffic that follows.

    Not called when the velocity controls are themselves the reason for the
    denial: those counts must stay up for the rest of the window, otherwise a
    detected loop immediately un-detects itself."""
    for key in (loop_key, burst_key):
        if key:
            await redis.eval(_RELEASE_VELOCITY_COUNTER, 1, key)

