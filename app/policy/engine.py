from app.models.agent import Agent
from app.policy.checks.policy_db import run_policy_checks
from app.policy.checks.quantitative import run_quantitative_checks
from app.policy.checks.semantic import run_semantic_checks
from app.policy.verdicts import TriangulationResult
from app.services.slm.client import LocalSlmClient


async def run_financial_triangulation(
    *,
    redis,
    slm_client: LocalSlmClient,
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
) -> TriangulationResult:
    quantitative = await run_quantitative_checks(
        redis=redis,
        agent=agent,
        amount_cents=amount_cents,
        asset_type=asset_type,
        network=network,
        destination_address=destination_address,
        fingerprint=fingerprint,
    )
    policy = run_policy_checks(
        agent=agent,
        amount_cents=amount_cents,
        vendor_url_or_name=vendor_url_or_name,
        asset_type=asset_type,
        stablecoin_symbol=stablecoin_symbol,
        network=network,
        destination_address=destination_address,
    )
    semantic = await run_semantic_checks(
        slm_client=slm_client,
        declared_goal=declared_goal,
        amount_cents=amount_cents,
        vendor_url_or_name=vendor_url_or_name,
        item_description=item_description,
        stablecoin_symbol=stablecoin_symbol,
        network=network,
        destination_address=destination_address,
    )

    reasons = [*quantitative.reasons, *policy.reasons, *semantic.reasons]
    if quantitative.hard_deny or policy.hard_deny or semantic.hard_deny:
        verdict = "MALICIOUS"
    elif quantitative.suspicious or policy.suspicious or semantic.suspicious:
        verdict = "SUSPICIOUS"
    else:
        verdict = "SAFE"

    return TriangulationResult(
        verdict=verdict,
        reasons=reasons,
        quantitative_result=quantitative.context,
        policy_result=policy.context,
        semantic_result=semantic.context,
    )

