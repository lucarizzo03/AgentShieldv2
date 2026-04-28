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
    dev_slm_preset: str | None = None,
) -> CheckResult:
    if dev_slm_preset is not None:
        result = {
            "alignment_label": dev_slm_preset.upper(),
            "risk_score": 10 if dev_slm_preset == "ALIGNED" else 55 if dev_slm_preset == "WEAK" else 85,
            "reason_codes": ["DEV_PRESET"],
        }
    else:
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
    alignment_label = str(raw_label).upper() if raw_label is not None else "WEAK"
    reason_codes = list(result.get("reason_codes", []))

    # Tinyllama numeric scores are unreliable — use only the label for decisions.
    # Clamp the stored score to a fixed range per label so the UI display is consistent.
    if alignment_label == "ALIGNED":
        risk_score = 10
    elif alignment_label == "WEAK":
        risk_score = 55
    else:
        risk_score = 85
        alignment_label = "MISMATCH"

    check = CheckResult()
    if alignment_label == "MISMATCH":
        check.suspicious = True
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

