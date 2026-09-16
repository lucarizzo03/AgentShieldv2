import hashlib
import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

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


_ADAPTIVE_OUTLIER_REASONS = {
    "ADAPTIVE_AMOUNT_OUTLIER",
    "ADAPTIVE_DAILY_SPEND_OUTLIER",
    "ADAPTIVE_HOURLY_RATE_OUTLIER",
    "ADAPTIVE_VENDOR_DIVERSITY_OUTLIER",
}


def adaptive_baseline_key(agent_id: str, asset_type: str, currency: str) -> str:
    return f"baseline:spend:{agent_id}:{asset_type}:{currency.strip().upper()}"


def _adaptive_baseline_context(
    key: str,
    *,
    sample_count: int = 0,
    historical_days: int = 0,
    evaluated: bool = False,
    signals: dict | None = None,
) -> dict:
    settings = get_settings()
    return {
        "key": key,
        "window_days": settings.adaptive_baseline_window_days,
        "sample_count": sample_count,
        "historical_days": historical_days,
        "minimum_samples": settings.adaptive_baseline_min_samples,
        "minimum_days": settings.adaptive_baseline_min_days,
        "evaluated": evaluated,
        "signals": signals or {},
    }


def _signal_stats(observed: float, history: list[float], z_score: float) -> dict:
    mean = statistics.fmean(history)
    stddev = statistics.pstdev(history, mean)
    threshold = max(mean + z_score * stddev, mean * 2.0)
    return {
        "observed": observed,
        "mean": round(mean, 4),
        "stddev": round(stddev, 4),
        "threshold": round(threshold, 4),
        "outlier": observed > threshold,
    }


async def _evaluate_adaptive_baseline(
    redis: Redis,
    *,
    agent_id: str,
    asset_type: str,
    currency: str,
    amount_cents: int,
    vendor: str,
    moment: datetime | None = None,
) -> tuple[list[str], dict]:
    settings = get_settings()
    key = adaptive_baseline_key(agent_id, asset_type, currency)
    now = moment or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=settings.adaptive_baseline_window_days)

    zrangebyscore = getattr(redis, "zrangebyscore", None)
    if not callable(zrangebyscore):
        return ["ADAPTIVE_BASELINE_INSUFFICIENT_HISTORY"], _adaptive_baseline_context(key)

    raw = await zrangebyscore(key, cutoff.timestamp(), now.timestamp(), withscores=True)

    observations: list[tuple[datetime, float, str]] = []
    for entry in raw or []:
        try:
            member, score = entry
            moment_seen = datetime.fromtimestamp(float(score), timezone.utc)
        except (TypeError, ValueError, OverflowError):
            continue
        if isinstance(member, bytes):
            member = member.decode("utf-8", errors="replace")
        try:
            payload = json.loads(member)
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        observed_amount = payload.get("amount_cents")
        observed_vendor = payload.get("vendor")
        if (
            not payload.get("request_id")
            or not isinstance(observed_amount, (int, float))
            or isinstance(observed_amount, bool)
            or observed_amount <= 0
            or not isinstance(observed_vendor, str)
        ):
            continue
        observations.append((moment_seen, float(observed_amount), observed_vendor.strip().lower()))

    sample_count = len(observations)
    today = now.date()
    completed_days = {seen.date() for seen, _, _ in observations if seen.date() < today}
    historical_days = len(completed_days)

    if (
        sample_count < settings.adaptive_baseline_min_samples
        or historical_days < settings.adaptive_baseline_min_days
    ):
        return ["ADAPTIVE_BASELINE_INSUFFICIENT_HISTORY"], _adaptive_baseline_context(
            key, sample_count=sample_count, historical_days=historical_days
        )

    current_hour = now.replace(minute=0, second=0, microsecond=0)
    day_totals: dict = defaultdict(float)
    day_vendors: dict = defaultdict(set)
    hour_counts: dict = defaultdict(int)
    current_day_spent = 0.0
    current_day_vendors: set = set()
    current_hour_count = 0
    for seen, observed_amount, observed_vendor in observations:
        if seen.date() == today:
            current_day_spent += observed_amount
            current_day_vendors.add(observed_vendor)
            if seen >= current_hour:
                current_hour_count += 1
        else:
            day_totals[seen.date()] += observed_amount
            day_vendors[seen.date()].add(observed_vendor)
            hour_counts[seen.replace(minute=0, second=0, microsecond=0)] += 1

    z = settings.adaptive_baseline_z_score_threshold
    candidate_vendor = vendor.strip().lower()
    signals = {
        "amount": _signal_stats(amount_cents, [amt for _, amt, _ in observations], z),
        "daily_spend": _signal_stats(
            current_day_spent + amount_cents, list(day_totals.values()), z
        ),
        "hourly_rate": _signal_stats(
            current_hour_count + 1, [float(c) for c in hour_counts.values()], z
        ),
        "vendor_diversity": _signal_stats(
            len(current_day_vendors | {candidate_vendor}),
            [float(len(v)) for v in day_vendors.values()],
            z,
        ),
    }

    reasons = []
    outlier_reasons = {
        "amount": "ADAPTIVE_AMOUNT_OUTLIER",
        "daily_spend": "ADAPTIVE_DAILY_SPEND_OUTLIER",
        "hourly_rate": "ADAPTIVE_HOURLY_RATE_OUTLIER",
        "vendor_diversity": "ADAPTIVE_VENDOR_DIVERSITY_OUTLIER",
    }
    for signal_name, signal in signals.items():
        if signal["outlier"]:
            reasons.append(outlier_reasons[signal_name])
    if not reasons:
        reasons.append("ADAPTIVE_BASELINE_NORMAL")

    return reasons, _adaptive_baseline_context(
        key,
        sample_count=sample_count,
        historical_days=historical_days,
        evaluated=True,
        signals=signals,
    )


async def record_adaptive_observation(
    redis: Redis,
    *,
    request_id: str,
    agent_id: str,
    asset_type: str,
    currency: str,
    amount_cents: int,
    vendor: str,
    moment: datetime | None = None,
) -> None:
    if not callable(getattr(redis, "zadd", None)):
        return
    settings = get_settings()
    key = adaptive_baseline_key(agent_id, asset_type, currency)
    now = moment or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=settings.adaptive_baseline_window_days)
    member = json.dumps(
        {
            "request_id": request_id,
            "amount_cents": amount_cents,
            "vendor": vendor.strip().lower(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    pipe = redis.pipeline(transaction=True)
    pipe.zadd(key, {member: now.timestamp()}, nx=True)
    pipe.zremrangebyscore(key, "-inf", cutoff.timestamp())
    pipe.zremrangebyrank(key, 0, -settings.adaptive_baseline_max_observations - 1)
    pipe.expire(key, settings.adaptive_baseline_window_days * 86400 + 86400)
    await pipe.execute()


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
    vendor_url_or_name: str = "",
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
        if loop_count > settings.loop_threshold:
            check.hard_deny = True
            check.reasons.append("LOOP_PATTERN_DETECTED")
        else:
            check.reasons.append("NO_LOOP_PATTERN")

        if burst_key:
            destination_burst = await redis.eval(_INCR_WITH_TTL, 1, burst_key, settings.loop_window_seconds)
            if destination_burst >= settings.loop_threshold:
                check.hard_deny = True
                check.reasons.append("DESTINATION_BURST_DETECTED")

        baseline_reasons, baseline_context = await _evaluate_adaptive_baseline(
            redis,
            agent_id=agent.agent_id,
            asset_type=asset_type,
            currency=agent.currency,
            amount_cents=amount_cents,
            vendor=vendor_url_or_name,
        )
    else:
        baseline_reasons = ["ADAPTIVE_BASELINE_INSUFFICIENT_HISTORY"]
        baseline_context = _adaptive_baseline_context(
            adaptive_baseline_key(agent.agent_id, asset_type, agent.currency)
        )

    check.reasons.extend(baseline_reasons)
    if _ADAPTIVE_OUTLIER_REASONS & set(baseline_reasons):
        check.suspicious = True

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
        "adaptive_baseline": baseline_context,
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

