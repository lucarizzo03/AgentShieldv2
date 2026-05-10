from app.core.config import get_settings
from app.policy.verdicts import CheckResult
from app.services.slm.client import AnthropicSemanticClient


async def run_semantic_checks(
    semantic_client: AnthropicSemanticClient,
    declared_goal: str,
    amount_cents: int,
    vendor_url_or_name: str,
    item_description: str,
    stablecoin_symbol: str | None,
    network: str | None,
    destination_address: str | None,
) -> CheckResult:
    result = await semantic_client.semantic_alignment(
        declared_goal=declared_goal,
        amount_cents=amount_cents,
        vendor_url_or_name=vendor_url_or_name,
        item_description=item_description,
        stablecoin_symbol=stablecoin_symbol,
        network=network,
        destination_address=destination_address,
    )

    raw_label = result.get("alignment_label")
    _score_raw = result.get("risk_score") or 0
    _score_float = float(_score_raw)
    # Claude occasionally returns a 0–1 decimal instead of 0–100 integer.
    # Values strictly between 0 and 1 are treated as fractional and scaled up.
    raw_score = int(round(_score_float * 100)) if 0 < _score_float < 1 else int(_score_float)
    alignment_label = str(raw_label).upper() if raw_label is not None else "WEAK"
    reason_codes = list(result.get("reason_codes", []))

    if raw_score >= 85 or alignment_label not in ("ALIGNED", "WEAK"):
        alignment_label = "MISMATCH"
        risk_score = 85
    elif alignment_label == "ALIGNED":
        risk_score = 10
    else:
        risk_score = 55

    settings = get_settings()
    check = CheckResult()
    if alignment_label == "MISMATCH":
        # Semantic mismatch is ambiguous by policy and should route to HITL.
        check.suspicious = True
        check.reasons.append("SEMANTIC_MISMATCH_HIGH")
    elif alignment_label == "WEAK":
        check.reasons.append("SEMANTIC_ALIGNMENT_WEAK")
        if raw_score >= settings.semantic_weak_suspicious_min_score:
            check.suspicious = True
    else:
        check.reasons.append("SEMANTIC_ALIGNMENT_HIGH")

    check.context = {
        "alignment_label": alignment_label,
        "risk_score": risk_score,
        "raw_risk_score": raw_score,
        "reason_codes": reason_codes,
    }
    return check
