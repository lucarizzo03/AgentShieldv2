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
    dev_preset: str | None = None,
) -> CheckResult:
    if dev_preset is not None:
        result = {
            "alignment_label": dev_preset.upper(),
            "risk_score": 10 if dev_preset == "ALIGNED" else 55 if dev_preset == "WEAK" else 85,
            "reason_codes": ["DEV_PRESET"],
        }
    else:
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
    raw_score = int(result.get("risk_score") or 0)
    alignment_label = str(raw_label).upper() if raw_label is not None else "WEAK"
    reason_codes = list(result.get("reason_codes", []))

    if raw_score >= 85 or alignment_label not in ("ALIGNED", "WEAK"):
        alignment_label = "MISMATCH"
        risk_score = 85
    elif alignment_label == "ALIGNED":
        risk_score = 10
    else:
        risk_score = 55

    check = CheckResult()
    if alignment_label == "MISMATCH":
        check.hard_deny = True
        check.reasons.append("SEMANTIC_MISMATCH_HIGH")
    elif alignment_label == "WEAK":
        check.reasons.append("SEMANTIC_ALIGNMENT_WEAK")
    else:
        check.reasons.append("SEMANTIC_ALIGNMENT_HIGH")

    check.context = {
        "alignment_label": alignment_label,
        "risk_score": risk_score,
        "reason_codes": reason_codes,
    }
    return check
