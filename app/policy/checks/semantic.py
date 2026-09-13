from app.policy.verdicts import CheckResult
from app.services.slm.client import AnthropicSemanticClient

# Thresholds operate on the 0-100 normalized alignment score (higher = more aligned = safer).
# >= 75  → ALIGNED  → safe
# 45-74  → WEAK     → suspicious (HITL)
# < 45   → MISMATCH → hard block
_SAFE_THRESHOLD = 75
_BLOCK_THRESHOLD = 45


def _coerce_risk_score(raw) -> int | None:
    """Normalize the model's risk score to an integer 0-100, or None if unusable."""
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    # Claude occasionally returns a 0–1 decimal instead of a 0–100 integer.
    # Values strictly between 0 and 1 are treated as fractional and scaled up.
    score = round(value * 100) if 0 < value < 1 else round(value)
    return max(0, min(100, int(score)))


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

    reason_codes = list(result.get("reason_codes", []))
    risk_score = _coerce_risk_score(result.get("risk_score"))
    evaluation_error = bool(result.get("evaluation_error", False)) or risk_score is None

    check = CheckResult()
    if evaluation_error:
        # The model never produced a usable judgement. Route to a human instead
        # of inventing a score — a provider outage must not hard-deny every spend.
        check.suspicious = True
        check.reasons.append("SEMANTIC_EVAL_UNAVAILABLE")
        check.context = {
            "alignment_label": "UNAVAILABLE",
            "risk_score": None,
            "raw_risk_score": None,
            "reason_codes": reason_codes,
            "evaluation_error": True,
        }
        return check

    # Claude returns a risk score (0=safe, 100=dangerous). Invert to an
    # alignment score (100=safe, 0=dangerous) so thresholds read naturally.
    raw_score = 100 - risk_score

    if raw_score >= _SAFE_THRESHOLD:
        alignment_label = "ALIGNED"
    elif raw_score >= _BLOCK_THRESHOLD:
        alignment_label = "WEAK"
    else:
        alignment_label = "MISMATCH"

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
        "evaluation_error": False,
    }
    return check
