import pytest

from app.models.agent import Agent
from app.policy.checks.goal_drift import run_goal_drift_check


class _FakeSemanticClient:
    def __init__(self, response=None, should_raise: bool = False):
        self._response = response or {}
        self._should_raise = should_raise

    async def goal_scope_check(self, **kwargs):
        if self._should_raise:
            raise RuntimeError("boom")
        return self._response


@pytest.mark.asyncio
async def test_goal_drift_skips_when_no_scopes() -> None:
    agent = Agent(agent_id="agent_goal_1", allowed_scopes=[])
    check = await run_goal_drift_check(
        agent=agent,
        declared_goal="Book a flight",
        semantic_client=_FakeSemanticClient(response={"within_scope": False}),
    )
    assert check.suspicious is False
    assert "GOAL_DRIFT_SKIPPED_NO_SCOPES" in check.reasons


@pytest.mark.asyncio
async def test_goal_drift_marks_suspicious_when_out_of_scope() -> None:
    agent = Agent(agent_id="agent_goal_2", allowed_scopes=["travel booking"])
    check = await run_goal_drift_check(
        agent=agent,
        declared_goal="Buy crypto",
        semantic_client=_FakeSemanticClient(
            response={"within_scope": False, "matched_scope": None, "confidence": 91, "reason": "outside scope"}
        ),
    )
    assert check.suspicious is True
    assert "GOAL_DRIFT_DETECTED" in check.reasons


@pytest.mark.asyncio
async def test_goal_drift_marks_suspicious_when_evaluation_unavailable() -> None:
    agent = Agent(agent_id="agent_goal_3", allowed_scopes=["travel booking"])
    check = await run_goal_drift_check(
        agent=agent,
        declared_goal="Book hotel",
        semantic_client=_FakeSemanticClient(should_raise=True),
    )
    assert check.suspicious is True
    assert "GOAL_DRIFT_EVAL_UNAVAILABLE" in check.reasons
