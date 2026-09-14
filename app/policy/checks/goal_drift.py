from app.core.config import get_settings
from app.models.agent import Agent
from app.policy.verdicts import CheckResult
from app.services.slm.client import AnthropicSemanticClient


def _coerce_confidence(raw) -> int:
    if isinstance(raw, bool) or raw is None:
        return 0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0
    score = round(value * 100) if 0 < value < 1 else round(value)
    return max(0, min(100, int(score)))


async def run_goal_drift_check(
    *,
    agent: Agent,
    declared_goal: str,
    semantic_client: AnthropicSemanticClient,
) -> CheckResult:
    check = CheckResult()

    if not agent.allowed_scopes:
        check.context = {"skipped": True, "reason": "no_scopes_defined"}
        check.reasons.append("GOAL_DRIFT_SKIPPED_NO_SCOPES")
        return check

    try:
        result = await semantic_client.goal_scope_check(
            declared_goal=declared_goal,
            allowed_scopes=agent.allowed_scopes,
        )
    except Exception:
        result = {"within_scope": False, "reason": "SLM_UNAVAILABLE", "evaluation_error": True}

    within_scope_raw = result.get("within_scope")
    evaluation_error = bool(result.get("evaluation_error", False))
    within_scope = bool(within_scope_raw) if isinstance(within_scope_raw, bool) else False
    if not isinstance(within_scope_raw, bool):
        evaluation_error = True

    confidence = _coerce_confidence(result.get("confidence"))
    min_confidence = get_settings().goal_drift_min_confidence
    low_confidence = not evaluation_error and confidence < min_confidence

    check.context = {
        "skipped": False,
        "within_scope": within_scope,
        "matched_scope": result.get("matched_scope"),
        "confidence": confidence,
        "min_confidence": min_confidence,
        "low_confidence": low_confidence,
        "reason": result.get("reason", ""),
        "allowed_scopes": agent.allowed_scopes,
        "evaluation_error": evaluation_error,
    }

    if evaluation_error:
        check.suspicious = True
        check.reasons.append("GOAL_DRIFT_EVAL_UNAVAILABLE")
    elif low_confidence:
        # An unsure "within scope" is not evidence of compliance, and an unsure
        # drift call is not evidence of drift; both belong with a human.
        check.suspicious = True
        check.reasons.append("GOAL_DRIFT_LOW_CONFIDENCE")
    elif within_scope:
        check.reasons.append("GOAL_WITHIN_SCOPE")
    else:
        check.suspicious = True
        check.reasons.append("GOAL_DRIFT_DETECTED")

    return check
