from app.models.agent import Agent
from app.policy.checks.policy_db import run_policy_checks
from app.policy.checks.quantitative import run_quantitative_checks
from app.policy.checks.semantic import run_semantic_checks
from app.policy.verdicts import TriangulationResult
from app.services.slm.client import AnthropicSemanticClient


_DEV_PRESET_VERDICT = {"ALIGNED": "SAFE", "WEAK": "SUSPICIOUS", "MISMATCH": "MALICIOUS"}


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
    dev_preset: str | None = None,
) -> TriangulationResult:
    if dev_preset and dev_preset.upper() in _DEV_PRESET_VERDICT:
        verdict = _DEV_PRESET_VERDICT[dev_preset.upper()]
        return TriangulationResult(
            verdict=verdict,
            reasons=["DEV_PRESET"],
            quantitative_result={"dev_preset": dev_preset},
            policy_result={"dev_preset": dev_preset},
            semantic_result={"alignment_label": dev_preset.upper(), "risk_score": 10 if verdict == "SAFE" else 55 if verdict == "SUSPICIOUS" else 85, "reason_codes": ["DEV_PRESET"]},
        )

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
        semantic_client=semantic_client,
        declared_goal=declared_goal,
        amount_cents=amount_cents,
        vendor_url_or_name=vendor_url_or_name,
        item_description=item_description,
        stablecoin_symbol=stablecoin_symbol,
        network=network,
        destination_address=destination_address,
        dev_preset=dev_preset,
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
