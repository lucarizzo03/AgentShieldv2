from app.models.agent import Agent
from app.policy.verdicts import CheckResult
from app.services.slm.client import AnthropicSemanticClient


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

    check.context = {
        "skipped": False,
        "within_scope": within_scope,
        "matched_scope": result.get("matched_scope"),
        "confidence": result.get("confidence", 0),
        "reason": result.get("reason", ""),
        "allowed_scopes": agent.allowed_scopes,
        "evaluation_error": evaluation_error,
    }

    if evaluation_error:
        check.suspicious = True
        check.reasons.append("GOAL_DRIFT_EVAL_UNAVAILABLE")
    elif within_scope:
        check.reasons.append("GOAL_WITHIN_SCOPE")
    else:
        check.suspicious = True
        check.reasons.append("GOAL_DRIFT_DETECTED")

    return check
