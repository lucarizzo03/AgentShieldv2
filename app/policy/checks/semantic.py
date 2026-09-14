from app.core.config import get_settings
from app.policy.verdicts import CheckResult
from app.services.slm.client import AnthropicSemanticClient

# Thresholds operate on the 0-100 normalized alignment score (higher = more aligned
# = safer) and come from settings; see Settings.semantic_aligned_min_score.


_LABELS = ("ALIGNED", "WEAK", "MISMATCH")


def _coerce_label(raw) -> str | None:
    if not isinstance(raw, str):
        return None
    label = raw.strip().upper()
    return label if label in _LABELS else None


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

    settings = get_settings()
    if raw_score >= settings.semantic_aligned_min_score:
        alignment_label = "ALIGNED"
    elif raw_score >= settings.semantic_weak_suspicious_min_score:
        alignment_label = "WEAK"
    else:
        alignment_label = "MISMATCH"

    model_label = _coerce_label(result.get("alignment_label"))
    # The model emits its label and its score independently; when the two
    # contradict each other neither is strong enough to auto-approve or
    # hard-block on, so the request goes to a human.
    label_disagreement = model_label is not None and model_label != alignment_label

    if label_disagreement:
        check.suspicious = True
        check.reasons.append("SEMANTIC_LABEL_SCORE_DISAGREEMENT")
    elif alignment_label == "MISMATCH":
        check.hard_deny = True
        check.reasons.append("SEMANTIC_MISMATCH_HIGH")
    elif alignment_label == "WEAK":
        check.suspicious = True
        check.reasons.append("SEMANTIC_ALIGNMENT_WEAK")
    else:
        check.reasons.append("SEMANTIC_ALIGNMENT_HIGH")

    check.context = {
        "alignment_label": alignment_label,
        "model_alignment_label": model_label,
        "label_disagreement": label_disagreement,
        "risk_score": raw_score,
        "raw_risk_score": raw_score,
        "reason_codes": reason_codes,
        "evaluation_error": False,
        "thresholds": {
            "aligned_min": settings.semantic_aligned_min_score,
            "weak_min": settings.semantic_weak_suspicious_min_score,
        },
    }
    return check
