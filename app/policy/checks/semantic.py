from app.policy.verdicts import CheckResult
from app.services.slm.client import AnthropicSemanticClient

# Thresholds operate on the 0-100 normalized score (higher = more aligned = safer).
# >= 75  → ALIGNED  → safe
# 45-75  → WEAK     → suspicious (HITL)
# <= 45  → MISMATCH → hard block
_SAFE_THRESHOLD = 75
_BLOCK_THRESHOLD = 45


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

    _score_raw = result.get("risk_score") or 0
    _score_float = float(_score_raw)
    # Claude occasionally returns a 0–1 decimal instead of 0–100 integer.
    # Values strictly between 0 and 1 are treated as fractional and scaled up.
    risk_score = int(round(_score_float * 100)) if 0 < _score_float < 1 else int(_score_float)
    # Claude returns a risk score (0=safe, 100=dangerous). Invert to an
    # alignment score (100=safe, 0=dangerous) so thresholds read naturally.
    raw_score = 100 - risk_score
    reason_codes = list(result.get("reason_codes", []))

    if raw_score >= _SAFE_THRESHOLD:
        alignment_label = "ALIGNED"
    elif raw_score > _BLOCK_THRESHOLD:
        alignment_label = "WEAK"
    else:
        alignment_label = "MISMATCH"

    check = CheckResult()
    if alignment_label == "MISMATCH":
        check.hard_deny = True
        check.reasons.append("SEMANTIC_MISMATCH_HIGH")
    elif alignment_label == "WEAK":
        check.suspicious = True
        check.reasons.append("SEMANTIC_ALIGNMENT_WEAK")
    else:
        check.reasons.append("SEMANTIC_ALIGNMENT_HIGH")

    check.context = {
        "alignment_label": alignment_label,
        "risk_score": raw_score,
        "raw_risk_score": raw_score,
        "reason_codes": reason_codes,
    }
    return check
