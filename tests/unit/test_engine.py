from datetime import datetime, timezone

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from app.models.agent import Agent
from app.policy.checks.quantitative import transaction_fingerprint
from app.policy.engine import run_financial_triangulation
from app.services.slm.client import AnthropicSemanticClient

REDIS_URL = "redis://localhost:6379/1"
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def redis():
    client = Redis.from_url(REDIS_URL, decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
def semantic():
    return AnthropicSemanticClient()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _kwargs(**overrides) -> dict:
    """Builds call kwargs with auto-computed fingerprint. Defaults to a clearly
    ALIGNED flight booking so tests that reach semantic get a reliable result."""
    base = dict(
        amount_cents=500,
        vendor_url_or_name="delta.com",
        item_description="Economy seat JFK-LAX",
        declared_goal="Book flight JFK to LAX",
        asset_type="FIAT",
        stablecoin_symbol=None,
        network=None,
        destination_address=None,
    )
    base.update(overrides)
    base["fingerprint"] = transaction_fingerprint(
        vendor=base["vendor_url_or_name"],
        amount_cents=base["amount_cents"],
        item_description=base["item_description"],
        asset_type=base["asset_type"],
        stablecoin_symbol=base.get("stablecoin_symbol"),
        network=base.get("network"),
        destination_address=base.get("destination_address"),
    )
    return base


# ---------------------------------------------------------------------------
# SAFE — full pipeline, real Claude call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_safe_verdict(redis, semantic) -> None:
    agent = _agent("e2e-safe-01")
    result = await run_financial_triangulation(
        redis=redis, semantic_client=semantic, agent=agent,
        **_kwargs(),
    )
    assert result.verdict == "SAFE"
    assert "BUDGET_WITHIN_LIMIT" in result.reasons
    assert "VENDOR_ALLOWED" in result.reasons
    assert result.semantic_result != {}
    assert result.goal_drift_result != {}


# ---------------------------------------------------------------------------
# Quantitative — budget exceeded (hard deny, semantic skipped)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_quant_budget_exceeded_hard_deny(redis, semantic) -> None:
    agent = _agent("e2e-budget-01", daily_budget_limit_cents=100)
    budget_key = f"budget:daily:{agent.agent_id}:FIAT:{TODAY}"
    await redis.set(budget_key, 100, ex=3600)

    result = await run_financial_triangulation(
        redis=redis, semantic_client=semantic, agent=agent,
        **_kwargs(amount_cents=200),
    )
    assert result.verdict == "MALICIOUS"
    assert "BUDGET_DAILY_LIMIT_EXCEEDED" in result.reasons
    assert result.semantic_result == {}
    assert result.goal_drift_result == {}

    await redis.delete(budget_key)


# ---------------------------------------------------------------------------
# Quantitative — loop pattern (suspicious, semantic still runs)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_loop_pattern_suspicious(redis, semantic) -> None:
    agent = _agent("e2e-loop-01")
    fp = transaction_fingerprint(
        vendor="loop-vendor.com", amount_cents=500,
        item_description="Economy seat JFK-LAX", asset_type="FIAT",
        stablecoin_symbol=None, network=None, destination_address=None,
    )
    loop_key = f"loop:txn:{agent.agent_id}:{fp}"
    await redis.set(loop_key, 4, ex=60)

    result = await run_financial_triangulation(
        redis=redis, semantic_client=semantic, agent=agent,
        **_kwargs(vendor_url_or_name="loop-vendor.com", fingerprint=fp),
    )
    assert result.verdict == "SUSPICIOUS"
    assert "LOOP_PATTERN_DETECTED" in result.reasons
    assert result.semantic_result != {}

    await redis.delete(loop_key)


# ---------------------------------------------------------------------------
# Quantitative — destination burst (suspicious, semantic still runs)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_destination_burst_suspicious(redis, semantic) -> None:
    agent = _agent("e2e-burst-01", allowed_stablecoins=["USDC"], allowed_networks=["base"])
    burst_key = f"dest:burst:{agent.agent_id}:base:0xburst000"
    await redis.set(burst_key, 4, ex=60)

    fp = transaction_fingerprint(
        vendor="delta.com", amount_cents=500,
        item_description="Economy seat JFK-LAX", asset_type="STABLECOIN",
        stablecoin_symbol="USDC", network="base", destination_address="0xburst000",
    )
    result = await run_financial_triangulation(
        redis=redis, semantic_client=semantic, agent=agent,
        **_kwargs(
            asset_type="STABLECOIN", stablecoin_symbol="USDC",
            network="base", destination_address="0xburst000",
            fingerprint=fp,
        ),
    )
    assert result.verdict == "SUSPICIOUS"
    assert "DESTINATION_BURST_DETECTED" in result.reasons
    assert result.semantic_result != {}

    await redis.delete(burst_key)


# ---------------------------------------------------------------------------
# Policy — vendor blocklist (hard deny, semantic skipped)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_policy_vendor_blocklist_hard_deny(redis, semantic) -> None:
    agent = _agent("e2e-blocklist-01", blocked_vendors=["evil.com"])
    result = await run_financial_triangulation(
        redis=redis, semantic_client=semantic, agent=agent,
        **_kwargs(vendor_url_or_name="evil.com"),
    )
    assert result.verdict == "MALICIOUS"
    assert "VENDOR_MATCHED_BLOCKLIST" in result.reasons
    assert result.semantic_result == {}
    assert result.goal_drift_result == {}


# ---------------------------------------------------------------------------
# Policy — phishing domain (hard deny, semantic skipped)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_policy_phishing_vendor_hard_deny(redis, semantic) -> None:
    agent = _agent("e2e-phish-01")
    result = await run_financial_triangulation(
        redis=redis, semantic_client=semantic, agent=agent,
        **_kwargs(vendor_url_or_name="https://xK9mQpZr2aBcDeFgHiJkLmNoPqRsTuV.payments.io"),
    )
    assert result.verdict == "MALICIOUS"
    assert "VENDOR_DOMAIN_PHISHING_PATTERN" in result.reasons
    assert result.semantic_result == {}
    assert result.goal_drift_result == {}


# ---------------------------------------------------------------------------
# Policy — stablecoin not allowed (hard deny, semantic skipped)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_policy_stablecoin_not_allowed_hard_deny(redis, semantic) -> None:
    agent = _agent("e2e-sc-01", allowed_stablecoins=["USDC"], allowed_networks=["base"])
    fp = transaction_fingerprint(
        vendor="delta.com", amount_cents=500,
        item_description="Economy seat JFK-LAX", asset_type="STABLECOIN",
        stablecoin_symbol="USDT", network="base", destination_address="0xabc000",
    )
    result = await run_financial_triangulation(
        redis=redis, semantic_client=semantic, agent=agent,
        **_kwargs(
            asset_type="STABLECOIN", stablecoin_symbol="USDT",
            network="base", destination_address="0xabc000",
            fingerprint=fp,
        ),
    )
    assert result.verdict == "MALICIOUS"
    assert "STABLECOIN_NOT_ALLOWED" in result.reasons
    assert result.semantic_result == {}


# ---------------------------------------------------------------------------
# Policy — network not allowed (hard deny, semantic skipped)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_policy_network_not_allowed_hard_deny(redis, semantic) -> None:
    agent = _agent("e2e-net-01", allowed_stablecoins=["USDC"], allowed_networks=["base"])
    fp = transaction_fingerprint(
        vendor="delta.com", amount_cents=500,
        item_description="Economy seat JFK-LAX", asset_type="STABLECOIN",
        stablecoin_symbol="USDC", network="ethereum", destination_address="0xabc000",
    )
    result = await run_financial_triangulation(
        redis=redis, semantic_client=semantic, agent=agent,
        **_kwargs(
            asset_type="STABLECOIN", stablecoin_symbol="USDC",
            network="ethereum", destination_address="0xabc000",
            fingerprint=fp,
        ),
    )
    assert result.verdict == "MALICIOUS"
    assert "NETWORK_NOT_ALLOWED" in result.reasons
    assert result.semantic_result == {}


# ---------------------------------------------------------------------------
# Policy — destination denylisted (hard deny, semantic skipped)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_policy_destination_denylisted_hard_deny(redis, semantic) -> None:
    agent = _agent(
        "e2e-denylist-01",
        allowed_stablecoins=["USDC"], allowed_networks=["base"],
        blocked_destination_addresses=["0xdeadbeef"],
    )
    fp = transaction_fingerprint(
        vendor="delta.com", amount_cents=500,
        item_description="Economy seat JFK-LAX", asset_type="STABLECOIN",
        stablecoin_symbol="USDC", network="base", destination_address="0xdeadbeef",
    )
    result = await run_financial_triangulation(
        redis=redis, semantic_client=semantic, agent=agent,
        **_kwargs(
            asset_type="STABLECOIN", stablecoin_symbol="USDC",
            network="base", destination_address="0xdeadbeef",
            fingerprint=fp,
        ),
    )
    assert result.verdict == "MALICIOUS"
    assert "DESTINATION_DENYLISTED" in result.reasons
    assert result.semantic_result == {}


# ---------------------------------------------------------------------------
# Policy — amount over threshold (suspicious, semantic still runs)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_policy_amount_over_threshold_suspicious(redis, semantic) -> None:
    agent = _agent("e2e-thresh-01", per_txn_auto_approve_limit_cents=100)
    result = await run_financial_triangulation(
        redis=redis, semantic_client=semantic, agent=agent,
        **_kwargs(amount_cents=200),
    )
    assert result.verdict == "SUSPICIOUS"
    assert "AMOUNT_OVER_AUTO_APPROVAL_THRESHOLD" in result.reasons
    assert result.semantic_result != {}


# ---------------------------------------------------------------------------
# Policy — destination not allowlisted (suspicious, semantic still runs)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_policy_destination_not_allowlisted_suspicious(redis, semantic) -> None:
    agent = _agent(
        "e2e-allowlist-01",
        allowed_stablecoins=["USDC"], allowed_networks=["base"],
        allowed_destination_addresses=["0xgood000"],
    )
    fp = transaction_fingerprint(
        vendor="delta.com", amount_cents=500,
        item_description="Economy seat JFK-LAX", asset_type="STABLECOIN",
        stablecoin_symbol="USDC", network="base", destination_address="0xother999",
    )
    result = await run_financial_triangulation(
        redis=redis, semantic_client=semantic, agent=agent,
        **_kwargs(
            asset_type="STABLECOIN", stablecoin_symbol="USDC",
            network="base", destination_address="0xother999",
            fingerprint=fp,
        ),
    )
    assert result.verdict == "SUSPICIOUS"
    assert "DESTINATION_NOT_ALLOWLISTED" in result.reasons
    assert result.semantic_result != {}


# ---------------------------------------------------------------------------
# Semantic — real Claude call, clear MISMATCH
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_semantic_mismatch_suspicious(redis, semantic) -> None:
    agent = _agent("e2e-sem-mismatch-01")
    result = await run_financial_triangulation(
        redis=redis, semantic_client=semantic, agent=agent,
        **_kwargs(
            declared_goal="Buy office supplies",
            vendor_url_or_name="binance.com",
            item_description="Token purchase",
        ),
    )
    assert result.verdict == "SUSPICIOUS"
    assert "SEMANTIC_MISMATCH_HIGH" in result.reasons


# ---------------------------------------------------------------------------
# Semantic — real Claude call, clear ALIGNED
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_semantic_aligned_safe(redis, semantic) -> None:
    agent = _agent("e2e-sem-aligned-01")
    result = await run_financial_triangulation(
        redis=redis, semantic_client=semantic, agent=agent,
        **_kwargs(
            declared_goal="Get current weather forecast for NYC trip planning",
            vendor_url_or_name="openweathermap.org",
            item_description="Weather API call for NYC coordinates",
            amount_cents=2,
        ),
    )
    assert result.verdict == "SAFE"
    assert "SEMANTIC_ALIGNMENT_HIGH" in result.reasons


# ---------------------------------------------------------------------------
# Goal drift — real Claude call, out of scope
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_goal_drift_detected_suspicious(redis, semantic) -> None:
    agent = _agent("e2e-drift-01", allowed_scopes=["travel bookings"])
    result = await run_financial_triangulation(
        redis=redis, semantic_client=semantic, agent=agent,
        **_kwargs(declared_goal="Buy crypto on exchange"),
    )
    assert result.verdict == "SUSPICIOUS"
    assert "GOAL_DRIFT_DETECTED" in result.reasons


# ---------------------------------------------------------------------------
# Goal drift — no scopes configured, skipped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_goal_drift_skipped_no_scopes(redis, semantic) -> None:
    agent = _agent("e2e-drift-skip-01", allowed_scopes=[])
    result = await run_financial_triangulation(
        redis=redis, semantic_client=semantic, agent=agent,
        **_kwargs(),
    )
    assert "GOAL_DRIFT_SKIPPED_NO_SCOPES" in result.reasons


# ---------------------------------------------------------------------------
# Goal drift — real Claude call, within scope
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_goal_within_scope_safe(redis, semantic) -> None:
    agent = _agent("e2e-drift-safe-01", allowed_scopes=["travel bookings"])
    result = await run_financial_triangulation(
        redis=redis, semantic_client=semantic, agent=agent,
        **_kwargs(
            declared_goal="Book flight JFK to LAX",
            vendor_url_or_name="delta.com",
            item_description="Economy seat JFK-LAX",
        ),
    )
    assert result.verdict == "SAFE"
    assert "GOAL_WITHIN_SCOPE" in result.reasons


# ---------------------------------------------------------------------------
# Parallel — both semantic and goal drift are called when quant/policy pass
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_semantic_and_goal_drift_both_called(redis) -> None:
    called = []

    class _TrackingClient(AnthropicSemanticClient):
        async def semantic_alignment(self, **kwargs):
            called.append("semantic")
            return await super().semantic_alignment(**kwargs)

        async def goal_scope_check(self, **kwargs):
            called.append("goal_drift")
            return await super().goal_scope_check(**kwargs)

    agent = _agent("e2e-parallel-01", allowed_scopes=["travel bookings"])
    await run_financial_triangulation(
        redis=redis,
        semantic_client=_TrackingClient(),
        agent=agent,
        **_kwargs(
            declared_goal="Book flight JFK to LAX",
            vendor_url_or_name="delta.com",
            item_description="Economy seat JFK-LAX",
        ),
    )
    assert "semantic" in called
    assert "goal_drift" in called
