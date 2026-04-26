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

    raw_label = result.get("alignment_label")
    alignment_label = str(raw_label).upper() if raw_label is not None else None
    risk_score = int(result.get("risk_score", 50))
    reason_codes = list(result.get("reason_codes", []))

    check = CheckResult()
    # Hard deny only on extremely high risk score — small local models (tinyllama) produce
    # unreliable MISMATCH labels on legitimate transactions, so the label alone never hard-denies.
    # MISMATCH label escalates to HITL (suspicious); only risk_score >= 90 is a hard block.
    if risk_score >= 90:
        check.hard_deny = True
        check.reasons.append("SEMANTIC_MISMATCH_HIGH")
    elif alignment_label in ("MISMATCH", "WEAK") or risk_score >= 50:
        check.suspicious = True
        check.reasons.append("SEMANTIC_MISMATCH_MEDIUM")
    else:
        check.reasons.append("SEMANTIC_ALIGNMENT_HIGH")

    alignment_label = alignment_label or "UNKNOWN"

    check.context = {
        "alignment_label": alignment_label,
        "risk_score": risk_score,
        "reason_codes": reason_codes,
    }
    return check

