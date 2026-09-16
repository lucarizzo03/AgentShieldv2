"""Check C provider-failure fallback.

When Anthropic is unreachable, returns garbage, or the circuit breaker is open,
Check C must degrade to a human review (SUSPICIOUS / HITL) — never auto-approve
(fail-open) and never hard-deny every spend (fail-closed).
"""
from types import SimpleNamespace

import pytest
import pytest_asyncio
from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.metrics import reset as reset_metrics
from app.core.metrics import snapshot
from app.models.agent import Agent
from app.policy.checks.quantitative import daily_budget_key
from app.policy.checks.semantic import run_semantic_checks
from app.policy.engine import run_financial_triangulation
from app.services.slm.client import (
    AnthropicSemanticClient,
    SlmCircuitBreaker,
    _semantic_unavailable,
)

REDIS_URL = "redis://localhost:6379/1"

_TXN = {
    "declared_goal": "Book flight JFK to LAX",
    "amount_cents": 500,
    "vendor_url_or_name": "delta.com",
    "item_description": "Economy seat JFK-LAX",
    "stablecoin_symbol": None,
    "network": None,
    "destination_address": None,
}


@pytest_asyncio.fixture
async def redis():
    client = Redis.from_url(REDIS_URL, decode_responses=True)
    yield client
    await client.aclose()


def _client_returning(monkeypatch, text: str | None = None, exc: Exception | None = None):
    client = AnthropicSemanticClient()

    async def _create(**_kwargs):
        if exc is not None:
            raise exc
        return SimpleNamespace(content=[SimpleNamespace(text=text)])

    monkeypatch.setattr(client._client.messages, "create", _create)
    monkeypatch.setattr(
        client, "_breaker", SlmCircuitBreaker(failure_threshold=3, cooldown_seconds=60)
    )
    return client


# ---------------------------------------------------------------------------
# Client-level fallback payload
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("reason", ["SLM_UNAVAILABLE", "SLM_CIRCUIT_OPEN", "SLM_UNEXPECTED_RESPONSE"])
def test_semantic_unavailable_payload_is_flagged_not_scored(reason) -> None:
    payload = _semantic_unavailable(reason)
    assert payload["evaluation_error"] is True
    assert payload["risk_score"] is None
    assert payload["alignment_label"] is None
    assert payload["reason_codes"] == [reason]


@pytest.mark.asyncio
async def test_provider_exception_returns_unavailable(monkeypatch) -> None:
    client = _client_returning(monkeypatch, exc=RuntimeError("provider down"))
    reset_metrics()

    result = await client.semantic_alignment(**_TXN)

    assert result["evaluation_error"] is True
    assert result["reason_codes"] == ["SLM_UNAVAILABLE"]
    assert client._breaker._consecutive_failures == 1
    assert snapshot().get("slm.semantic.failure") == 1


@pytest.mark.asyncio
async def test_unparseable_response_returns_unavailable_without_tripping_breaker(
    monkeypatch,
) -> None:
    client = _client_returning(monkeypatch, text="I cannot evaluate this transaction.")

    result = await client.semantic_alignment(**_TXN)

    assert result["evaluation_error"] is True
    assert result["reason_codes"] == ["SLM_UNEXPECTED_RESPONSE"]
    assert client._breaker._consecutive_failures == 0


@pytest.mark.asyncio
async def test_json_without_alignment_label_returns_unavailable(monkeypatch) -> None:
    client = _client_returning(monkeypatch, text='{"foo": "bar"}')

    result = await client.semantic_alignment(**_TXN)

    assert result["evaluation_error"] is True
    assert result["reason_codes"] == ["SLM_UNEXPECTED_RESPONSE"]


@pytest.mark.asyncio
async def test_good_response_is_passed_through(monkeypatch) -> None:
    client = _client_returning(
        monkeypatch,
        text='```json\n{"alignment_label": "ALIGNED", "risk_score": 5, "reason_codes": ["OK"]}\n```',
    )
    result = await client.semantic_alignment(**_TXN)
    assert result == {"alignment_label": "ALIGNED", "risk_score": 5, "reason_codes": ["OK"]}
    assert "evaluation_error" not in result


@pytest.mark.asyncio
async def test_open_breaker_returns_unavailable_with_circuit_reason(monkeypatch) -> None:
    client = _client_returning(monkeypatch, exc=RuntimeError("provider down"))
    client._breaker = SlmCircuitBreaker(failure_threshold=1, cooldown_seconds=60)
    reset_metrics()

    first = await client.semantic_alignment(**_TXN)
    second = await client.semantic_alignment(**_TXN)

    assert first["reason_codes"] == ["SLM_UNAVAILABLE"]
    assert second["reason_codes"] == ["SLM_CIRCUIT_OPEN"]
    assert second["evaluation_error"] is True
    assert snapshot().get("slm.semantic.short_circuited") == 1


# ---------------------------------------------------------------------------
# Check C consumes the fallback → SUSPICIOUS, never SAFE, never hard-deny
# ---------------------------------------------------------------------------

class _StubClient:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def semantic_alignment(self, **_kwargs) -> dict:
        return self._payload

    async def goal_scope_check(self, **_kwargs) -> dict:
        return {"within_scope": True, "matched_scope": "travel", "confidence": 99, "reason": "ok"}


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["SLM_UNAVAILABLE", "SLM_CIRCUIT_OPEN", "SLM_UNEXPECTED_RESPONSE"])
async def test_check_c_routes_fallback_to_hitl(reason) -> None:
    check = await run_semantic_checks(semantic_client=_StubClient(_semantic_unavailable(reason)), **_TXN)

    assert check.suspicious is True
    assert check.hard_deny is False
    assert check.reasons == ["SEMANTIC_EVAL_UNAVAILABLE"]
    assert check.context["alignment_label"] == "UNAVAILABLE"
    assert check.context["risk_score"] is None
    assert check.context["evaluation_error"] is True
    assert check.context["reason_codes"] == [reason]


@pytest.mark.asyncio
async def test_check_c_does_not_invent_a_score_on_fallback() -> None:
    """A fabricated ALIGNED/low-risk payload would silently auto-approve every
    spend during an outage; the fallback must not be scoreable."""
    settings = get_settings()
    check = await run_semantic_checks(semantic_client=_StubClient(_semantic_unavailable("SLM_UNAVAILABLE")), **_TXN)
    assert "SEMANTIC_ALIGNMENT_HIGH" not in check.reasons
    assert "thresholds" not in check.context
    assert settings.semantic_aligned_min_score > 0  # guard: thresholds are in effect


# ---------------------------------------------------------------------------
# Engine-level: outage → SUSPICIOUS verdict, degraded metric emitted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_engine_verdict_is_suspicious_when_check_c_unavailable(redis) -> None:
    agent = Agent(
        agent_id="checkc-fallback-01",
        daily_budget_limit_cents=100_000,
        per_transaction_limit_cents=50_000,
        allowed_scopes=[],
    )
    budget_key = daily_budget_key(agent.agent_id, "FIAT")
    await redis.delete(budget_key)
    reset_metrics()

    result = await run_financial_triangulation(
        redis=redis,
        semantic_client=_StubClient(_semantic_unavailable("SLM_UNAVAILABLE")),
        agent=agent,
        amount_cents=500,
        vendor_url_or_name="delta.com",
        item_description="Economy seat",
        declared_goal="Book flight JFK to LAX",
        asset_type="FIAT",
        stablecoin_symbol=None,
        network=None,
        destination_address=None,
        fingerprint="fp-checkc-fallback-01",
    )

    assert result.verdict == "SUSPICIOUS"
    assert "SEMANTIC_EVAL_UNAVAILABLE" in result.reasons
    assert result.semantic_result["evaluation_error"] is True
    assert result.semantic_result["reason_codes"] == ["SLM_UNAVAILABLE"]
    assert snapshot().get("engine.model.degraded") == 1

    await redis.delete(budget_key, f"loop:txn:{agent.agent_id}:fp-checkc-fallback-01")
