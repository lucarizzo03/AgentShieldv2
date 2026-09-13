import asyncio
import logging

from app.core.config import get_settings
from app.core.metrics import increment
from app.models.agent import Agent
from app.policy.checks.goal_drift import run_goal_drift_check
from app.policy.checks.policy_db import run_policy_checks
from app.policy.checks.quantitative import run_quantitative_checks
from app.policy.checks.semantic import run_semantic_checks
from app.policy.verdicts import CheckResult, TriangulationResult
from app.services.slm.client import AnthropicSemanticClient

logger = logging.getLogger(__name__)


def _deadline_exceeded_results() -> tuple[CheckResult, CheckResult]:
    semantic = CheckResult(
        suspicious=True,
        reasons=["SEMANTIC_EVAL_UNAVAILABLE"],
        context={
            "alignment_label": "UNAVAILABLE",
            "risk_score": None,
            "raw_risk_score": None,
            "reason_codes": ["SLM_DEADLINE_EXCEEDED"],
            "evaluation_error": True,
        },
    )
    goal_drift = CheckResult(
        suspicious=True,
        reasons=["GOAL_DRIFT_EVAL_UNAVAILABLE"],
        context={
            "skipped": False,
            "within_scope": False,
            "matched_scope": None,
            "confidence": 0,
            "reason": "SLM_DEADLINE_EXCEEDED",
            "evaluation_error": True,
        },
    )
    return semantic, goal_drift


async def run_financial_triangulation(
    *,
    redis,
    semantic_client: AnthropicSemanticClient,
    agent: Agent,
    amount_cents: int,
    vendor_url_or_name: str,
    item_description: str,
    declared_goal: str,
    asset_type: str,
    stablecoin_symbol: str | None,
    network: str | None,
    destination_address: str | None,
    fingerprint: str,
    currency: str | None = None,
    reservation_id: str | None = None,
) -> TriangulationResult:
    """``fingerprint`` keys the loop check, so callers should pass the velocity
    fingerprint rather than the amount-bound idempotency one.  ``reservation_id``
    tags the budget reservation so an abandoned one can be reconciled."""
    quantitative = await run_quantitative_checks(
        redis=redis,
        agent=agent,
        amount_cents=amount_cents,
        asset_type=asset_type,
        network=network,
        destination_address=destination_address,
        fingerprint=fingerprint,
        reservation_id=reservation_id,
    )
    policy = run_policy_checks(
        agent=agent,
        amount_cents=amount_cents,
        vendor_url_or_name=vendor_url_or_name,
        asset_type=asset_type,
        stablecoin_symbol=stablecoin_symbol,
        network=network,
        destination_address=destination_address,
        currency=currency,
    )

    if quantitative.hard_deny or policy.hard_deny:
        return TriangulationResult(
            verdict="MALICIOUS",
            reasons=[*quantitative.reasons, *policy.reasons],
            quantitative_result=quantitative.context,
            policy_result=policy.context,
            semantic_result={},
            goal_drift_result={},
        )

    # Both model calls carry their own SDK timeout; this is the backstop so a
    # provider that accepts the connection and then stalls cannot hold the
    # worker past a known bound. Blowing the deadline degrades to HITL.
    try:
        semantic, goal_drift = await asyncio.wait_for(
            asyncio.gather(
                run_semantic_checks(
                    semantic_client=semantic_client,
                    declared_goal=declared_goal,
                    amount_cents=amount_cents,
                    vendor_url_or_name=vendor_url_or_name,
                    item_description=item_description,
                    stablecoin_symbol=stablecoin_symbol,
                    network=network,
                    destination_address=destination_address,
                ),
                run_goal_drift_check(
                    agent=agent,
                    declared_goal=declared_goal,
                    semantic_client=semantic_client,
                ),
            ),
            timeout=get_settings().slm_deadline_seconds,
        )
    except asyncio.TimeoutError:
        increment("slm.deadline_exceeded")
        logger.warning("Semantic evaluation exceeded deadline; degrading to HITL")
        semantic, goal_drift = _deadline_exceeded_results()

    reasons = [*quantitative.reasons, *policy.reasons, *semantic.reasons, *goal_drift.reasons]
    if semantic.hard_deny or goal_drift.hard_deny:
        verdict = "MALICIOUS"
    elif quantitative.suspicious or policy.suspicious or semantic.suspicious or goal_drift.suspicious:
        verdict = "SUSPICIOUS"
    else:
        verdict = "SAFE"

    return TriangulationResult(
        verdict=verdict,
        reasons=reasons,
        quantitative_result=quantitative.context,
        policy_result=policy.context,
        semantic_result=semantic.context,
        goal_drift_result=goal_drift.context,
    )
