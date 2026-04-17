from app.models.agent import Agent
from app.policy.verdicts import CheckResult
from app.services.payment.stablecoin_policy import validate_stablecoin_policy


def _contains_vendor_match(blocked_vendors: list[str], vendor: str) -> bool:
    candidate = vendor.lower().strip()
    return any(entry.lower().strip() in candidate for entry in blocked_vendors)


def run_policy_checks(
    agent: Agent,
    amount_cents: int,
    vendor_url_or_name: str,
    asset_type: str,
    stablecoin_symbol: str | None,
    network: str | None,
    destination_address: str | None,
) -> CheckResult:
    check = CheckResult()

    vendor_blocked = _contains_vendor_match(agent.blocked_vendors, vendor_url_or_name)
    if vendor_blocked:
        check.hard_deny = True
        check.reasons.append("VENDOR_MATCHED_BLOCKLIST")
    else:
        check.reasons.append("VENDOR_ALLOWED")

    threshold = agent.hitl_required_over_cents or agent.per_txn_auto_approve_limit_cents
    amount_over_threshold = amount_cents > threshold
    if amount_over_threshold:
        check.suspicious = True
        check.reasons.append("AMOUNT_OVER_AUTO_APPROVAL_THRESHOLD")
    else:
        check.reasons.append("AMOUNT_WITHIN_AUTO_APPROVAL_THRESHOLD")

    stablecoin_check = validate_stablecoin_policy(
        agent=agent,
        asset_type=asset_type,
        stablecoin_symbol=stablecoin_symbol,
        network=network,
        destination_address=destination_address,
    )
    check.hard_deny = check.hard_deny or stablecoin_check.hard_deny
    check.suspicious = check.suspicious or stablecoin_check.suspicious
    check.reasons.extend(stablecoin_check.reasons)

    check.context = {
        "vendor_blocked": vendor_blocked,
        "amount_over_threshold": amount_over_threshold,
        "threshold_cents": threshold,
        "stablecoin": stablecoin_check.context,
    }
    return check

