"""Metrics export (#22) and shadow evaluation of Checks C/D (#28)."""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from redis.asyncio import Redis

from app.core import metrics
from app.core.config import get_settings
from app.main import app
from app.models.agent import Agent
from app.policy.checks.quantitative import transaction_fingerprint
from app.policy.engine import run_financial_triangulation
from app.policy.verdicts import CheckResult

REDIS_URL = "redis://localhost:6379/1"


@pytest_asyncio.fixture
async def redis():
    client = Redis.from_url(REDIS_URL, decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture(autouse=True)
def _clean_metrics():
    metrics.reset()
    yield
    metrics.reset()


def test_counters_and_histograms_render_as_prometheus_text():
    metrics.increment("spend.verdict.safe")
    metrics.increment("spend.verdict.safe")
    metrics.observe("engine.total.latency", 0.2)
    metrics.observe("engine.total.latency", 3.0)

    text = metrics.render_prometheus()

    assert "# TYPE agentshield_spend_verdict_safe_total counter" in text
    assert "agentshield_spend_verdict_safe_total 2" in text
    assert 'agentshield_engine_total_latency_seconds_bucket{le="0.25"} 1' in text
    assert 'agentshield_engine_total_latency_seconds_bucket{le="5.0"} 2' in text
    assert 'agentshield_engine_total_latency_seconds_bucket{le="+Inf"} 2' in text
    assert "agentshield_engine_total_latency_seconds_count 2" in text


def test_histogram_snapshot_reports_quantiles():
    for value in (0.1, 0.2, 0.3, 10.0):
        metrics.observe("engine.check.model.latency", value)

    stats = metrics.histogram_snapshot()["engine.check.model.latency"]
    assert stats["count"] == 4
    assert stats["p50"] == 0.3
    assert stats["p99"] == 10.0


def test_metrics_endpoint_is_open_in_dev_and_token_gated_otherwise(monkeypatch):
    metrics.increment("spend.verdict.malicious")
    settings = get_settings()

    with TestClient(app) as client:
        monkeypatch.setattr(settings, "app_env", "dev", raising=False)
        monkeypatch.setattr(settings, "metrics_auth_token", "", raising=False)
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "agentshield_spend_verdict_malicious_total 1" in resp.text

        monkeypatch.setattr(settings, "app_env", "prod", raising=False)
        assert client.get("/metrics").status_code == 404

        monkeypatch.setattr(settings, "metrics_auth_token", "scrape-me", raising=False)
        assert client.get("/metrics").status_code == 401
        authorized = client.get("/metrics", headers={"Authorization": "Bearer scrape-me"})
        assert authorized.status_code == 200


def _agent() -> Agent:
    return Agent(
        agent_id="shadow-01",
        daily_budget_limit_cents=100_000,
        per_txn_auto_approve_limit_cents=100_000,
        blocked_vendors=["evil.com"],
        allowed_stablecoins=["USDC"],
        allowed_networks=["base"],
        allowed_destination_addresses=[],
        blocked_destination_addresses=[],
        allowed_scopes=["travel bookings"],
        currency="USD",
    )


def _call_kwargs() -> dict:
    base = {
        "amount_cents": 500,
        "vendor_url_or_name": "evil.com",
        "item_description": "Gift cards",
        "declared_goal": "Book flight JFK to LAX",
        "asset_type": "FIAT",
        "stablecoin_symbol": None,
        "network": None,
        "destination_address": None,
    }
    base["fingerprint"] = transaction_fingerprint(
        vendor=base["vendor_url_or_name"],
        amount_cents=base["amount_cents"],
        item_description=base["item_description"],
        asset_type=base["asset_type"],
        stablecoin_symbol=None,
        network=None,
        destination_address=None,
    )
    return base


@pytest.mark.asyncio
async def test_hard_denied_request_records_shadow_evaluation(redis, monkeypatch):
    async def fake_semantic(**_kwargs):
        return CheckResult(reasons=["SEMANTIC_ALIGNMENT_HIGH"], context={"alignment_label": "ALIGNED"})

    async def fake_goal_drift(**_kwargs):
        return CheckResult(reasons=["GOAL_WITHIN_SCOPE"], context={"within_scope": True})

    monkeypatch.setattr("app.policy.engine.run_semantic_checks", fake_semantic)
    monkeypatch.setattr("app.policy.engine.run_goal_drift_check", fake_goal_drift)
    monkeypatch.setattr("app.policy.engine.random.random", lambda: 0.0)

    result = await run_financial_triangulation(
        redis=redis, semantic_client=None, agent=_agent(), **_call_kwargs()
    )

    # The deterministic denial is untouched; the model results are recorded only.
    assert result.verdict == "MALICIOUS"
    assert "VENDOR_MATCHED_BLOCKLIST" in result.reasons
    assert "SEMANTIC_ALIGNMENT_HIGH" not in result.reasons
    assert result.semantic_result["shadow"] is True
    assert result.semantic_result["shadow_reasons"] == ["SEMANTIC_ALIGNMENT_HIGH"]
    assert result.goal_drift_result["shadow"] is True
    assert metrics.snapshot()["engine.shadow_eval.disagreed"] == 1


@pytest.mark.asyncio
async def test_shadow_evaluation_is_sampled_out_by_default(redis, monkeypatch):
    async def unexpected(**_kwargs):
        raise AssertionError("Checks C/D must not run when the request is not sampled")

    monkeypatch.setattr("app.policy.engine.run_semantic_checks", unexpected)
    monkeypatch.setattr("app.policy.engine.run_goal_drift_check", unexpected)
    monkeypatch.setattr("app.policy.engine.random.random", lambda: 0.99)

    result = await run_financial_triangulation(
        redis=redis, semantic_client=None, agent=_agent(), **_call_kwargs()
    )

    assert result.verdict == "MALICIOUS"
    assert result.semantic_result == {}
    assert result.goal_drift_result == {}


@pytest.mark.asyncio
async def test_shadow_evaluation_failure_leaves_the_denial_intact(redis, monkeypatch):
    async def broken(**_kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr("app.policy.engine.run_semantic_checks", broken)
    monkeypatch.setattr("app.policy.engine.run_goal_drift_check", broken)
    monkeypatch.setattr("app.policy.engine.random.random", lambda: 0.0)

    result = await run_financial_triangulation(
        redis=redis, semantic_client=None, agent=_agent(), **_call_kwargs()
    )

    assert result.verdict == "MALICIOUS"
    assert result.semantic_result == {}
    assert metrics.snapshot()["engine.shadow_eval.failed"] == 1
