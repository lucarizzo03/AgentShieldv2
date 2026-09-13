"""Model-signal handling (#24) and verdict provenance (#23)."""

import pytest

from app.core.config import get_settings
from app.models.agent import Agent
from app.policy.checks.goal_drift import run_goal_drift_check
from app.policy.checks.semantic import run_semantic_checks
from app.policy.provenance import ENGINE_VERSION, engine_provenance


class _FakeSemanticClient:
    def __init__(self, semantic=None, scope=None):
        self._semantic = semantic or {}
        self._scope = scope or {}

    async def semantic_alignment(self, **kwargs):
        return self._semantic

    async def goal_scope_check(self, **kwargs):
        return self._scope


async def _semantic(response: dict):
    return await run_semantic_checks(
        semantic_client=_FakeSemanticClient(semantic=response),
        declared_goal="Book a flight",
        amount_cents=1_000,
        vendor_url_or_name="delta.com",
        item_description="Economy seat",
        stablecoin_symbol=None,
        network=None,
        destination_address=None,
    )


async def _goal_drift(response: dict):
    return await run_goal_drift_check(
        agent=Agent(agent_id="agent_signals", allowed_scopes=["travel bookings"]),
        declared_goal="Book a flight",
        semantic_client=_FakeSemanticClient(scope=response),
    )


@pytest.mark.asyncio
async def test_model_label_contradicting_safe_score_goes_to_hitl() -> None:
    check = await _semantic(
        {"alignment_label": "MISMATCH", "risk_score": 5, "reason_codes": []}
    )
    assert check.suspicious is True
    assert check.hard_deny is False
    assert "SEMANTIC_LABEL_SCORE_DISAGREEMENT" in check.reasons
    assert check.context["model_alignment_label"] == "MISMATCH"
    assert check.context["alignment_label"] == "ALIGNED"


@pytest.mark.asyncio
async def test_model_label_contradicting_blocking_score_does_not_hard_deny() -> None:
    check = await _semantic(
        {"alignment_label": "ALIGNED", "risk_score": 95, "reason_codes": []}
    )
    assert check.hard_deny is False
    assert check.suspicious is True
    assert "SEMANTIC_LABEL_SCORE_DISAGREEMENT" in check.reasons


@pytest.mark.asyncio
async def test_agreeing_label_and_score_keep_their_verdict() -> None:
    safe = await _semantic({"alignment_label": "ALIGNED", "risk_score": 5, "reason_codes": []})
    assert safe.suspicious is False and safe.hard_deny is False

    blocked = await _semantic({"alignment_label": "MISMATCH", "risk_score": 95, "reason_codes": []})
    assert blocked.hard_deny is True
    assert blocked.context["label_disagreement"] is False


@pytest.mark.asyncio
async def test_unusable_model_label_is_ignored_rather_than_flagged() -> None:
    check = await _semantic({"alignment_label": "banana", "risk_score": 5, "reason_codes": []})
    assert check.suspicious is False
    assert check.context["model_alignment_label"] is None


@pytest.mark.asyncio
async def test_low_confidence_within_scope_routes_to_hitl() -> None:
    check = await _goal_drift(
        {"within_scope": True, "matched_scope": "travel bookings", "confidence": 20}
    )
    assert check.suspicious is True
    assert "GOAL_DRIFT_LOW_CONFIDENCE" in check.reasons
    assert "GOAL_WITHIN_SCOPE" not in check.reasons


@pytest.mark.asyncio
async def test_confident_within_scope_stays_clean() -> None:
    check = await _goal_drift(
        {"within_scope": True, "matched_scope": "travel bookings", "confidence": 95}
    )
    assert check.suspicious is False
    assert "GOAL_WITHIN_SCOPE" in check.reasons


@pytest.mark.asyncio
async def test_goal_drift_confidence_floor_is_configurable(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "goal_drift_min_confidence", 10, raising=True)
    check = await _goal_drift(
        {"within_scope": True, "matched_scope": "travel bookings", "confidence": 20}
    )
    assert check.suspicious is False
    assert check.context["min_confidence"] == 10


@pytest.mark.asyncio
async def test_fractional_confidence_is_scaled() -> None:
    check = await _goal_drift(
        {"within_scope": True, "matched_scope": "travel bookings", "confidence": 0.95}
    )
    assert check.context["confidence"] == 95
    assert check.suspicious is False


def test_provenance_records_engine_model_prompts_and_thresholds() -> None:
    settings = get_settings()
    provenance = engine_provenance()
    assert provenance["engine_version"] == ENGINE_VERSION
    assert provenance["model_name"] == settings.anthropic_model_name
    assert len(provenance["prompt_versions"]["semantic_alignment"]) == 12
    assert (
        provenance["prompt_versions"]["semantic_alignment"]
        != provenance["prompt_versions"]["goal_scope"]
    )
    assert provenance["thresholds"]["semantic_aligned_min_score"] == settings.semantic_aligned_min_score
    assert provenance["thresholds"]["goal_drift_min_confidence"] == settings.goal_drift_min_confidence


def test_provenance_tracks_threshold_changes(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "semantic_aligned_min_score", 91, raising=True)
    assert engine_provenance()["thresholds"]["semantic_aligned_min_score"] == 91
