from app.policy.verdicts import CheckResult
from app.services.slm.client import LocalSlmClient


async def run_semantic_checks(
    slm_client: LocalSlmClient,
    declared_goal: str,
    amount_cents: int,
    vendor_url_or_name: str,
    item_description: str,
    stablecoin_symbol: str | None,
    network: str | None,
    destination_address: str | None,
) -> CheckResult:
    result = await slm_client.semantic_alignment(
        declared_goal=declared_goal,
        amount_cents=amount_cents,
        vendor_url_or_name=vendor_url_or_name,
        item_description=item_description,
        stablecoin_symbol=stablecoin_symbol,
        network=network,
        destination_address=destination_address,
    )

    alignment_label = str(result.get("alignment_label", "WEAK")).upper()
    risk_score = int(result.get("risk_score", 50))
    reason_codes = list(result.get("reason_codes", []))

    check = CheckResult()
    if alignment_label == "MISMATCH" or risk_score >= 85:
        check.hard_deny = True
        check.reasons.append("SEMANTIC_MISMATCH_HIGH")
    elif alignment_label == "WEAK" or risk_score >= 50:
        check.suspicious = True
        check.reasons.append("SEMANTIC_MISMATCH_MEDIUM")
    else:
        check.reasons.append("SEMANTIC_ALIGNMENT_HIGH")

    check.context = {
        "alignment_label": alignment_label,
        "risk_score": risk_score,
        "reason_codes": reason_codes,
    }
    return check

