import asyncio
import logging
import random
import time

from app.core.config import get_settings
from app.core.metrics import increment, observe
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


async def _shadow_evaluate(
    *,
    semantic_client: AnthropicSemanticClient,
    agent: Agent,
    declared_goal: str,
    amount_cents: int,
    vendor_url_or_name: str,
    item_description: str,
    stablecoin_symbol: str | None,
    network: str | None,
    destination_address: str | None,
) -> tuple[dict, dict]:
    """Evaluate Checks C/D on a request the deterministic checks already denied.

    The denial stands either way: the results are recorded so the transactions
    most worth labelling stop being the only ones with no model evaluation, and
    so C/D can be scored against A/B. Sampled, and any failure yields nothing
    rather than disturbing a decision that has already been made.
    """
    settings = get_settings()
    if random.random() >= settings.shadow_eval_sample_rate:
        return {}, {}

    started = time.perf_counter()
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
            timeout=settings.slm_deadline_seconds,
        )
    except Exception as exc:  # shadow evaluation must never disturb the denial
        increment("engine.shadow_eval.failed")
        logger.warning("Shadow evaluation failed on short-circuited request", exc_info=exc)
        return {}, {}

    increment("engine.shadow_eval.completed")
    observe("engine.shadow_eval.latency", time.perf_counter() - started)
    if semantic.hard_deny or goal_drift.hard_deny:
        increment("engine.shadow_eval.agreed_deny")
    else:
        increment("engine.shadow_eval.disagreed")

    return (
        {**semantic.context, "shadow": True, "shadow_reasons": semantic.reasons},
        {**goal_drift.context, "shadow": True, "shadow_reasons": goal_drift.reasons},
    )


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
    started = time.perf_counter()
    check_started = started
    quantitative = await run_quantitative_checks(
        redis=redis,
        agent=agent,
        amount_cents=amount_cents,
        asset_type=asset_type,
        network=network,
        destination_address=destination_address,
        fingerprint=fingerprint,
        vendor_url_or_name=vendor_url_or_name,
        reservation_id=reservation_id,
    )
    observe("engine.check.quantitative.latency", time.perf_counter() - check_started)

    check_started = time.perf_counter()
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
    observe("engine.check.policy.latency", time.perf_counter() - check_started)

    if quantitative.hard_deny or policy.hard_deny:
        increment("engine.short_circuited")
        semantic_shadow, goal_drift_shadow = await _shadow_evaluate(
            semantic_client=semantic_client,
            agent=agent,
            declared_goal=declared_goal,
            amount_cents=amount_cents,
            vendor_url_or_name=vendor_url_or_name,
            item_description=item_description,
            stablecoin_symbol=stablecoin_symbol,
            network=network,
            destination_address=destination_address,
        )
        observe("engine.total.latency", time.perf_counter() - started)
        return TriangulationResult(
            verdict="MALICIOUS",
            reasons=[*quantitative.reasons, *policy.reasons],
            quantitative_result=quantitative.context,
            policy_result=policy.context,
            semantic_result=semantic_shadow,
            goal_drift_result=goal_drift_shadow,
        )

    # Both model calls carry their own SDK timeout; this is the backstop so a
    # provider that accepts the connection and then stalls cannot hold the
    # worker past a known bound. Blowing the deadline degrades to HITL.
    check_started = time.perf_counter()
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
    except TimeoutError:
        increment("slm.deadline_exceeded")
        logger.warning("Semantic evaluation exceeded deadline; degrading to HITL")
        semantic, goal_drift = _deadline_exceeded_results()
    observe("engine.check.model.latency", time.perf_counter() - check_started)

    if semantic.context.get("evaluation_error") or goal_drift.context.get("evaluation_error"):
        increment("engine.model.degraded")

    reasons = [*quantitative.reasons, *policy.reasons, *semantic.reasons, *goal_drift.reasons]
    if semantic.hard_deny or goal_drift.hard_deny:
        verdict = "MALICIOUS"
    elif quantitative.suspicious or policy.suspicious or semantic.suspicious or goal_drift.suspicious:
        verdict = "SUSPICIOUS"
    else:
        verdict = "SAFE"

    observe("engine.total.latency", time.perf_counter() - started)

    return TriangulationResult(
        verdict=verdict,
        reasons=reasons,
        quantitative_result=quantitative.context,
        policy_result=policy.context,
        semantic_result=semantic.context,
        goal_drift_result=goal_drift.context,
    )
