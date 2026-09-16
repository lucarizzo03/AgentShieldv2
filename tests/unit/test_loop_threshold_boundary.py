"""Boundary tests for Check A velocity controls: the loop detector and the
destination-burst detector must trip on exactly the LOOP_THRESHOLD-th request
inside the window (`count >= threshold`), never one request later."""
import pytest
import pytest_asyncio
from redis.asyncio import Redis

from app.core.config import get_settings
from app.models.agent import Agent
from app.policy.checks.quantitative import (
    daily_budget_key,
    run_quantitative_checks,
    transaction_fingerprint,
)

REDIS_URL = "redis://localhost:6379/1"


@pytest_asyncio.fixture
async def redis():
    client = Redis.from_url(REDIS_URL, decode_responses=True)
    yield client
    await client.aclose()


def _agent(agent_id: str, **kwargs) -> Agent:
    defaults = dict(
        agent_id=agent_id,
        daily_budget_limit_cents=10_000_000,
        per_txn_auto_approve_limit_cents=10_000,
        blocked_vendors=[],
        allowed_stablecoins=["USDC"],
        allowed_networks=["base"],
        allowed_destination_addresses=[],
        blocked_destination_addresses=[],
        allowed_scopes=[],
    )
    defaults.update(kwargs)
    return Agent(**defaults)


def _fingerprint(agent_id: str) -> str:
    return transaction_fingerprint(
        vendor="vendor.example", amount_cents=500, item_description=f"item-{agent_id}",
        asset_type="FIAT", stablecoin_symbol=None, network=None, destination_address=None,
    )


async def _run(redis, agent, fingerprint, **overrides):
    kwargs = dict(
        redis=redis, agent=agent, amount_cents=500, asset_type="FIAT",
        network=None, destination_address=None, fingerprint=fingerprint,
    )
    kwargs.update(overrides)
    return await run_quantitative_checks(**kwargs)


@pytest.mark.asyncio
async def test_loop_trips_on_exactly_the_threshold_th_request(redis) -> None:
    agent = _agent("loop-boundary-01")
    threshold = get_settings().loop_threshold
    fp = _fingerprint(agent.agent_id)
    loop_key = f"loop:txn:{agent.agent_id}:{fp}"
    budget_key = daily_budget_key(agent.agent_id, "FIAT")
    await redis.delete(budget_key, loop_key)

    for i in range(1, threshold):
        result = await _run(redis, agent, fp)
        assert not result.hard_deny, f"request {i} must not trip the loop detector"
        assert "NO_LOOP_PATTERN" in result.reasons
        assert "LOOP_PATTERN_DETECTED" not in result.reasons

    result = await _run(redis, agent, fp)
    assert result.hard_deny
    assert "LOOP_PATTERN_DETECTED" in result.reasons
    assert "NO_LOOP_PATTERN" not in result.reasons
    assert int(await redis.get(loop_key)) == threshold

    await redis.delete(budget_key, loop_key)


@pytest.mark.asyncio
async def test_loop_stays_tripped_past_the_threshold(redis) -> None:
    agent = _agent("loop-boundary-02")
    threshold = get_settings().loop_threshold
    fp = _fingerprint(agent.agent_id)
    loop_key = f"loop:txn:{agent.agent_id}:{fp}"
    budget_key = daily_budget_key(agent.agent_id, "FIAT")
    await redis.delete(budget_key, loop_key)

    for _ in range(threshold):
        await _run(redis, agent, fp)

    result = await _run(redis, agent, fp)
    assert result.hard_deny
    assert "LOOP_PATTERN_DETECTED" in result.reasons
    assert int(await redis.get(loop_key)) == threshold + 1

    await redis.delete(budget_key, loop_key)


@pytest.mark.asyncio
async def test_loop_counter_carries_window_ttl(redis) -> None:
    agent = _agent("loop-boundary-03")
    settings = get_settings()
    fp = _fingerprint(agent.agent_id)
    loop_key = f"loop:txn:{agent.agent_id}:{fp}"
    budget_key = daily_budget_key(agent.agent_id, "FIAT")
    await redis.delete(budget_key, loop_key)

    await _run(redis, agent, fp)
    ttl = await redis.ttl(loop_key)
    assert 0 < ttl <= settings.loop_window_seconds

    await redis.delete(budget_key, loop_key)


@pytest.mark.asyncio
async def test_distinct_fingerprints_do_not_share_a_loop_counter(redis) -> None:
    agent = _agent("loop-boundary-04")
    threshold = get_settings().loop_threshold
    fp_a = _fingerprint(agent.agent_id)
    fp_b = transaction_fingerprint(
        vendor="other.example", amount_cents=500, item_description="other",
        asset_type="FIAT", stablecoin_symbol=None, network=None, destination_address=None,
    )
    key_a = f"loop:txn:{agent.agent_id}:{fp_a}"
    key_b = f"loop:txn:{agent.agent_id}:{fp_b}"
    budget_key = daily_budget_key(agent.agent_id, "FIAT")
    await redis.delete(budget_key, key_a, key_b)

    for _ in range(threshold):
        await _run(redis, agent, fp_a)

    result = await _run(redis, agent, fp_b)
    assert not result.hard_deny
    assert "NO_LOOP_PATTERN" in result.reasons

    await redis.delete(budget_key, key_a, key_b)


@pytest.mark.asyncio
async def test_destination_burst_trips_at_the_same_boundary(redis) -> None:
    agent = _agent("loop-boundary-05")
    threshold = get_settings().loop_threshold
    network, address = "base", "0xBURST"
    burst_key = f"dest:burst:{agent.agent_id}:{network}:{address}"
    budget_key = daily_budget_key(agent.agent_id, "STABLECOIN")
    loop_keys = []
    await redis.delete(budget_key, burst_key)

    for i in range(1, threshold + 1):
        fp = transaction_fingerprint(
            vendor="vendor.example", amount_cents=500 + i, item_description=f"burst-{i}",
            asset_type="STABLECOIN", stablecoin_symbol="USDC", network=network,
            destination_address=address,
        )
        loop_keys.append(f"loop:txn:{agent.agent_id}:{fp}")
        result = await _run(
            redis, agent, fp, amount_cents=500 + i, asset_type="STABLECOIN",
            network=network, destination_address=address,
        )
        if i < threshold:
            assert "DESTINATION_BURST_DETECTED" not in result.reasons
            assert not result.hard_deny
        else:
            assert "DESTINATION_BURST_DETECTED" in result.reasons
            assert result.hard_deny
        assert "LOOP_PATTERN_DETECTED" not in result.reasons

    await redis.delete(budget_key, burst_key, *loop_keys)


@pytest.mark.asyncio
async def test_budget_exceeded_skips_loop_counting(redis) -> None:
    agent = _agent("loop-boundary-06", daily_budget_limit_cents=100)
    fp = _fingerprint(agent.agent_id)
    loop_key = f"loop:txn:{agent.agent_id}:{fp}"
    budget_key = daily_budget_key(agent.agent_id, "FIAT")
    await redis.delete(budget_key, loop_key)

    result = await _run(redis, agent, fp)
    assert result.hard_deny
    assert "BUDGET_DAILY_LIMIT_EXCEEDED" in result.reasons
    assert "LOOP_PATTERN_DETECTED" not in result.reasons
    assert "NO_LOOP_PATTERN" not in result.reasons
    assert await redis.get(loop_key) is None

    await redis.delete(budget_key, loop_key)
