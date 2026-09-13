"""Reliability regressions for the check engine: degraded semantic evaluation,
atomic idempotency, and bounded budget rollback."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from app.policy.checks.quantitative import (
    daily_budget_key,
    rollback_budget_reservation,
)
from app.policy.checks.semantic import run_semantic_checks
from app.services.idempotency import (
    cache_idempotent_response,
    claim_idempotency_slot,
    release_idempotency_slot,
)

REDIS_URL = "redis://localhost:6379/1"


@pytest_asyncio.fixture
async def redis():
    client = Redis.from_url(REDIS_URL, decode_responses=True)
    yield client
    await client.aclose()


class _StubSemanticClient:
    def __init__(self, payload: dict):
        self._payload = payload

    async def semantic_alignment(self, **_kwargs) -> dict:
        return self._payload


async def _semantic(payload: dict):
    return await run_semantic_checks(
        semantic_client=_StubSemanticClient(payload),
        declared_goal="Book flight JFK to LAX",
        amount_cents=500,
        vendor_url_or_name="delta.com",
        item_description="Economy seat JFK-LAX",
        stablecoin_symbol=None,
        network=None,
        destination_address=None,
    )


# ---------------------------------------------------------------------------
# Semantic check — degraded model must escalate, never hard-deny
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_semantic_provider_outage_routes_to_hitl() -> None:
    check = await _semantic(
        {"alignment_label": None, "risk_score": None,
         "reason_codes": ["SLM_UNAVAILABLE"], "evaluation_error": True}
    )
    assert check.suspicious is True
    assert check.hard_deny is False
    assert "SEMANTIC_EVAL_UNAVAILABLE" in check.reasons
    assert check.context["alignment_label"] == "UNAVAILABLE"


@pytest.mark.asyncio
@pytest.mark.parametrize("score", ["not-a-number", None, True, {"nested": 1}])
async def test_semantic_malformed_score_does_not_raise(score) -> None:
    check = await _semantic({"risk_score": score, "reason_codes": []})
    assert check.suspicious is True
    assert check.hard_deny is False
    assert "SEMANTIC_EVAL_UNAVAILABLE" in check.reasons


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("risk_score", "label", "hard_deny", "suspicious"),
    [
        (25, "ALIGNED", False, False),
        (26, "WEAK", False, True),
        (55, "WEAK", False, True),  # the old SLM fallback score
        (56, "MISMATCH", True, False),
        (0.9, "MISMATCH", True, False),  # fractional 0-1 form
        (500, "MISMATCH", True, False),  # clamped to 100
        (-20, "ALIGNED", False, False),  # clamped to 0
    ],
)
async def test_semantic_score_boundaries(risk_score, label, hard_deny, suspicious) -> None:
    check = await _semantic({"risk_score": risk_score, "reason_codes": []})
    assert check.context["alignment_label"] == label
    assert check.hard_deny is hard_deny
    assert check.suspicious is suspicious


# ---------------------------------------------------------------------------
# Idempotency — atomic claim and payload binding
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_claims_yield_one_owner(redis) -> None:
    key = f"idem-concurrent-{datetime.now(timezone.utc).timestamp()}"
    results = await asyncio.gather(
        *[claim_idempotency_slot(redis, "agent-1", key, "fp-a") for _ in range(10)]
    )
    owners = [r for r in results if r is None]
    assert len(owners) == 1
    assert all(r.state == "in_flight" for r in results if r is not None)

    await redis.delete(f"idempotency:agent-1:{key}")


@pytest.mark.asyncio
async def test_same_key_different_payload_is_detected(redis) -> None:
    key = f"idem-mismatch-{datetime.now(timezone.utc).timestamp()}"
    assert await claim_idempotency_slot(redis, "agent-1", key, "fp-a") is None
    await cache_idempotent_response(
        redis, "agent-1", key, {"_http_status": 200, "body": {"request_id": "req_1"}}, "fp-a"
    )

    replay = await claim_idempotency_slot(redis, "agent-1", key, "fp-a")
    assert replay is not None
    assert replay.state == "completed"
    assert replay.response["body"]["request_id"] == "req_1"

    conflicting = await claim_idempotency_slot(redis, "agent-1", key, "fp-b")
    assert conflicting is not None
    assert conflicting.fingerprint == "fp-a"

    await redis.delete(f"idempotency:agent-1:{key}")


@pytest.mark.asyncio
async def test_released_claim_can_be_retried(redis) -> None:
    key = f"idem-release-{datetime.now(timezone.utc).timestamp()}"
    assert await claim_idempotency_slot(redis, "agent-1", key, "fp-a") is None
    await release_idempotency_slot(redis, "agent-1", key)
    assert await claim_idempotency_slot(redis, "agent-1", key, "fp-a") is None

    await redis.delete(f"idempotency:agent-1:{key}")


@pytest.mark.asyncio
async def test_release_does_not_drop_a_completed_decision(redis) -> None:
    key = f"idem-keep-{datetime.now(timezone.utc).timestamp()}"
    await cache_idempotent_response(
        redis, "agent-1", key, {"_http_status": 200, "body": {"request_id": "req_1"}}, "fp-a"
    )
    await release_idempotency_slot(redis, "agent-1", key)
    assert await redis.exists(f"idempotency:agent-1:{key}") == 1

    await redis.delete(f"idempotency:agent-1:{key}")


# ---------------------------------------------------------------------------
# Budget rollback — bounded, TTL-preserving, date-pinned
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rollback_never_goes_negative_and_keeps_ttl(redis) -> None:
    key = daily_budget_key("agent-rollback-01", "FIAT")
    await redis.set(key, 300, ex=3600)

    await rollback_budget_reservation(redis, key, 500)
    assert int(await redis.get(key)) == 0
    assert 0 < await redis.ttl(key) <= 3600

    await redis.delete(key)


@pytest.mark.asyncio
async def test_rollback_of_expired_key_does_not_recreate_it(redis) -> None:
    key = daily_budget_key("agent-rollback-02", "FIAT")
    await redis.delete(key)

    await rollback_budget_reservation(redis, key, 500)
    assert await redis.exists(key) == 0


@pytest.mark.asyncio
async def test_rollback_targets_the_reserved_day_not_today(redis) -> None:
    """A request that reserves just before UTC midnight must roll back against
    the key it reserved on, not the freshly-rolled-over one."""
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    reserved_key = daily_budget_key("agent-rollback-03", "FIAT", yesterday)
    today_key = daily_budget_key("agent-rollback-03", "FIAT")
    await redis.set(reserved_key, 500, ex=3600)
    await redis.set(today_key, 700, ex=3600)

    await rollback_budget_reservation(redis, reserved_key, 500)
    assert int(await redis.get(reserved_key)) == 0
    assert int(await redis.get(today_key)) == 700

    await redis.delete(reserved_key, today_key)
