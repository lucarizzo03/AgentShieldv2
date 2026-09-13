"""Reliability regressions for reservation leaks, velocity rollback, model
deadlines and the SLM circuit breaker."""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from app.core.config import get_settings
from app.models.agent import Agent
from app.policy.checks.quantitative import (
    RESERVATION_MARKER_PREFIX,
    daily_budget_key,
    release_velocity_counters,
    reservation_marker_key,
    rollback_budget_reservation,
    run_quantitative_checks,
    transaction_fingerprint,
    velocity_fingerprint,
)
from app.policy.engine import run_financial_triangulation
from app.services.budget_reconciler import release_outstanding_reservation
from app.services.slm.client import AnthropicSemanticClient, SlmCircuitBreaker

REDIS_URL = "redis://localhost:6379/1"


@pytest_asyncio.fixture
async def redis():
    client = Redis.from_url(REDIS_URL, decode_responses=True)
    yield client
    await client.aclose()


def _agent(agent_id: str, **kwargs) -> Agent:
    defaults = dict(
        agent_id=agent_id,
        daily_budget_limit_cents=100_000,
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


# ---------------------------------------------------------------------------
# Budget reservations — discoverable and releasable after a crash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reservation_writes_a_discoverable_marker(redis) -> None:
    agent = _agent("res-marker-01")
    budget_key = daily_budget_key(agent.agent_id, "FIAT")
    marker_key = reservation_marker_key("req_marker_01")
    await redis.delete(budget_key, marker_key)

    check = await run_quantitative_checks(
        redis=redis, agent=agent, amount_cents=500, asset_type="FIAT",
        network=None, destination_address=None, fingerprint="fp-marker-01",
        reservation_id="req_marker_01",
    )

    assert check.context["reservation_marker_key"] == marker_key
    marker = json.loads(await redis.get(marker_key))
    assert marker["budget_key"] == budget_key
    assert marker["amount_cents"] == 500

    await redis.delete(budget_key, marker_key, check.context["loop_key"])


@pytest.mark.asyncio
async def test_abandoned_reservation_is_released_from_its_marker(redis) -> None:
    """A crash between reserve and rollback leaves the counter consumed; the
    marker is what makes that budget recoverable."""
    agent = _agent("res-marker-02")
    budget_key = daily_budget_key(agent.agent_id, "FIAT")
    marker_key = reservation_marker_key("req_marker_02")
    await redis.delete(budget_key, marker_key)

    check = await run_quantitative_checks(
        redis=redis, agent=agent, amount_cents=700, asset_type="FIAT",
        network=None, destination_address=None, fingerprint="fp-marker-02",
        reservation_id="req_marker_02",
    )
    assert int(await redis.get(budget_key)) == 700

    assert await release_outstanding_reservation(redis, "req_marker_02") is True
    assert int(await redis.get(budget_key)) == 0
    assert await redis.exists(marker_key) == 0

    await redis.delete(budget_key, check.context["loop_key"])


@pytest.mark.asyncio
async def test_reservation_cannot_be_released_twice(redis) -> None:
    agent = _agent("res-marker-03")
    budget_key = daily_budget_key(agent.agent_id, "FIAT")
    await redis.delete(budget_key, reservation_marker_key("req_marker_03"))

    check = await run_quantitative_checks(
        redis=redis, agent=agent, amount_cents=900, asset_type="FIAT",
        network=None, destination_address=None, fingerprint="fp-marker-03",
        reservation_id="req_marker_03",
    )

    assert await release_outstanding_reservation(redis, "req_marker_03") is True
    assert await release_outstanding_reservation(redis, "req_marker_03") is False
    assert int(await redis.get(budget_key)) == 0

    await redis.delete(budget_key, check.context["loop_key"])


@pytest.mark.asyncio
async def test_rollback_clears_the_marker_so_the_reconciler_skips_it(redis) -> None:
    agent = _agent("res-marker-04")
    budget_key = daily_budget_key(agent.agent_id, "FIAT")
    marker_key = reservation_marker_key("req_marker_04")
    await redis.delete(budget_key, marker_key)

    check = await run_quantitative_checks(
        redis=redis, agent=agent, amount_cents=400, asset_type="FIAT",
        network=None, destination_address=None, fingerprint="fp-marker-04",
        reservation_id="req_marker_04",
    )
    await rollback_budget_reservation(redis, budget_key, 400, marker_key)

    assert await redis.exists(marker_key) == 0
    assert await release_outstanding_reservation(redis, "req_marker_04") is False
    assert int(await redis.get(budget_key)) == 0

    await redis.delete(budget_key, check.context["loop_key"])


@pytest.mark.asyncio
async def test_marker_key_is_namespaced_by_reservation(redis) -> None:
    assert reservation_marker_key("req_x").startswith(RESERVATION_MARKER_PREFIX)
    assert reservation_marker_key("req_x") != reservation_marker_key("req_y")


# ---------------------------------------------------------------------------
# Velocity counters — released when the request never executed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_velocity_counters_are_given_back(redis) -> None:
    loop_key = "loop:txn:vel-01:fp"
    burst_key = "dest:burst:vel-01:base:0xabc"
    await redis.delete(loop_key, burst_key)
    await redis.set(loop_key, 3, ex=60)
    await redis.set(burst_key, 2, ex=60)

    await release_velocity_counters(redis, loop_key, burst_key)

    assert int(await redis.get(loop_key)) == 2
    assert int(await redis.get(burst_key)) == 1

    await redis.delete(loop_key, burst_key)


@pytest.mark.asyncio
async def test_velocity_release_drops_the_key_at_zero(redis) -> None:
    loop_key = "loop:txn:vel-02:fp"
    await redis.delete(loop_key)
    await redis.set(loop_key, 1, ex=60)

    await release_velocity_counters(redis, loop_key, None)
    assert await redis.exists(loop_key) == 0

    # An extra release must not resurrect the key with a negative count.
    await release_velocity_counters(redis, loop_key, None)
    assert await redis.exists(loop_key) == 0


@pytest.mark.asyncio
async def test_velocity_fingerprint_ignores_amount_and_item() -> None:
    """The idempotency fingerprint must stay amount-bound, but a loop that
    varies the amount by a cent is still the same loop."""
    a = velocity_fingerprint(
        vendor="vendor.example", asset_type="STABLECOIN",
        stablecoin_symbol="USDC", network="base", destination_address="0xABC",
    )
    b = velocity_fingerprint(
        vendor="Vendor.Example", asset_type="STABLECOIN",
        stablecoin_symbol="USDC", network="base", destination_address="0xabc",
    )
    assert a == b

    txn_a = transaction_fingerprint(
        vendor="vendor.example", amount_cents=100, item_description="x",
        asset_type="STABLECOIN", stablecoin_symbol="USDC", network="base",
        destination_address="0xABC",
    )
    txn_b = transaction_fingerprint(
        vendor="vendor.example", amount_cents=101, item_description="x",
        asset_type="STABLECOIN", stablecoin_symbol="USDC", network="base",
        destination_address="0xABC",
    )
    assert txn_a != txn_b


@pytest.mark.asyncio
async def test_loop_check_fires_on_amount_varying_repeats(redis) -> None:
    agent = _agent("vel-loop-01", daily_budget_limit_cents=10_000_000)
    settings = get_settings()
    fingerprint = velocity_fingerprint(
        vendor="vendor.example", asset_type="FIAT",
        stablecoin_symbol=None, network=None, destination_address=None,
    )
    budget_key = daily_budget_key(agent.agent_id, "FIAT")
    loop_key = f"loop:txn:{agent.agent_id}:{fingerprint}"
    await redis.delete(budget_key, loop_key)

    results = []
    for i in range(settings.loop_threshold):
        results.append(await run_quantitative_checks(
            redis=redis, agent=agent, amount_cents=500 + i, asset_type="FIAT",
            network=None, destination_address=None, fingerprint=fingerprint,
        ))

    assert all("LOOP_PATTERN_DETECTED" not in r.reasons for r in results[:-1])
    assert "LOOP_PATTERN_DETECTED" in results[-1].reasons

    await redis.delete(budget_key, loop_key)


# ---------------------------------------------------------------------------
# SLM circuit breaker
# ---------------------------------------------------------------------------

def test_breaker_opens_after_threshold_and_closes_after_cooldown() -> None:
    breaker = SlmCircuitBreaker(failure_threshold=3, cooldown_seconds=0.05)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.is_open is False

    breaker.record_failure()
    assert breaker.is_open is True


def test_breaker_success_resets_the_failure_run() -> None:
    breaker = SlmCircuitBreaker(failure_threshold=2, cooldown_seconds=60)
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    assert breaker.is_open is False


@pytest.mark.asyncio
async def test_breaker_lets_one_probe_through_after_cooldown() -> None:
    breaker = SlmCircuitBreaker(failure_threshold=1, cooldown_seconds=0.05)
    breaker.record_failure()
    assert breaker.is_open is True

    await asyncio.sleep(0.06)
    assert breaker.is_open is False


@pytest.mark.asyncio
async def test_open_breaker_short_circuits_without_calling_anthropic(monkeypatch) -> None:
    client = AnthropicSemanticClient()
    calls = 0

    async def _fail(**_kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("provider down")

    monkeypatch.setattr(client._client.messages, "create", _fail)
    monkeypatch.setattr(
        client, "_breaker", SlmCircuitBreaker(failure_threshold=2, cooldown_seconds=60)
    )

    for _ in range(4):
        result = await client.semantic_alignment(
            declared_goal="Book flight", amount_cents=500,
            vendor_url_or_name="delta.com", item_description="seat",
            stablecoin_symbol=None, network=None, destination_address=None,
        )
        assert result["evaluation_error"] is True

    assert calls == 2
    assert result["reason_codes"] == ["SLM_CIRCUIT_OPEN"]


# ---------------------------------------------------------------------------
# Overall deadline on Checks C/D
# ---------------------------------------------------------------------------

class _HangingSemanticClient:
    async def semantic_alignment(self, **_kwargs) -> dict:
        await asyncio.sleep(30)
        raise AssertionError("deadline should have fired")

    async def goal_scope_check(self, **_kwargs) -> dict:
        await asyncio.sleep(30)
        raise AssertionError("deadline should have fired")


@pytest.mark.asyncio
async def test_slow_model_degrades_to_hitl_instead_of_hanging(redis, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "slm_deadline_seconds", 0.1, raising=True)
    agent = _agent("slm-deadline-01", allowed_scopes=["travel"])
    budget_key = daily_budget_key(agent.agent_id, "FIAT")
    await redis.delete(budget_key)

    started = datetime.now(timezone.utc)
    result = await run_financial_triangulation(
        redis=redis, semantic_client=_HangingSemanticClient(), agent=agent,
        amount_cents=500, vendor_url_or_name="delta.com",
        item_description="Economy seat", declared_goal="Book flight JFK to LAX",
        asset_type="FIAT", stablecoin_symbol=None, network=None,
        destination_address=None, fingerprint="fp-deadline-01",
    )
    elapsed = datetime.now(timezone.utc) - started

    assert elapsed < timedelta(seconds=5)
    assert result.verdict == "SUSPICIOUS"
    assert "SEMANTIC_EVAL_UNAVAILABLE" in result.reasons
    assert result.semantic_result["reason_codes"] == ["SLM_DEADLINE_EXCEEDED"]

    await redis.delete(budget_key, f"loop:txn:{agent.agent_id}:fp-deadline-01")
