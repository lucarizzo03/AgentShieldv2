import hashlib
from datetime import datetime, timezone

from redis.asyncio import Redis

from app.core.config import get_settings
from app.db.redis import seconds_until_next_utc_midnight
from app.models.agent import Agent
from app.policy.verdicts import CheckResult


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


async def run_quantitative_checks(
    redis: Redis,
    agent: Agent,
    amount_cents: int,
    asset_type: str,
    network: str | None,
    destination_address: str | None,
    fingerprint: str,
) -> CheckResult:
    settings = get_settings()
    check = CheckResult()

    date_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    budget_key = f"budget:daily:{agent.agent_id}:{asset_type}:{date_key}"
    loop_key = f"loop:txn:{agent.agent_id}:{fingerprint}"
    burst_key = (
        f"dest:burst:{agent.agent_id}:{network}:{destination_address}"
        if network and destination_address
        else None
    )

    current_spent = int(await redis.get(budget_key) or 0)
    projected = current_spent + amount_cents
    budget_exceeded = projected > agent.daily_budget_limit_cents
    if budget_exceeded:
        check.hard_deny = True
        check.reasons.append("BUDGET_DAILY_LIMIT_EXCEEDED")
    else:
        check.reasons.append("BUDGET_WITHIN_LIMIT")

    loop_count = await redis.incr(loop_key)
    if loop_count == 1:
        await redis.expire(loop_key, settings.loop_window_seconds)
    if loop_count >= settings.loop_threshold:
        check.suspicious = True
        check.reasons.append("LOOP_PATTERN_DETECTED")
    else:
        check.reasons.append("NO_LOOP_PATTERN")

    destination_burst = 0
    if burst_key:
        destination_burst = await redis.incr(burst_key)
        if destination_burst == 1:
            await redis.expire(burst_key, settings.loop_window_seconds)
        if destination_burst >= settings.loop_threshold:
            check.suspicious = True
            check.reasons.append("DESTINATION_BURST_DETECTED")

    check.context = {
        "daily_spent_usd": round(current_spent / 100, 2),
        "projected_spent_usd": round(projected / 100, 2),
        "budget_exceeded": budget_exceeded,
        "loop_count": int(loop_count),
        "destination_burst_count": int(destination_burst),
    }
    return check


async def commit_budget_spend(redis: Redis, agent_id: str, asset_type: str, amount_cents: int) -> None:
    date_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    budget_key = f"budget:daily:{agent_id}:{asset_type}:{date_key}"
    await redis.incrby(budget_key, amount_cents)
    await redis.expire(budget_key, seconds_until_next_utc_midnight())

