from app.models.agent import Agent
from app.policy.verdicts import CheckResult


def normalize_addr(address: str | None) -> str:
    return (address or "").strip().lower()


def validate_stablecoin_policy(
    agent: Agent,
    asset_type: str,
    stablecoin_symbol: str | None,
    network: str | None,
    destination_address: str | None,
) -> CheckResult:
    check = CheckResult()
    if asset_type != "STABLECOIN":
        check.context = {"asset_type": asset_type}
        return check

    if stablecoin_symbol not in set(agent.allowed_stablecoins):
        check.hard_deny = True
        check.reasons.append("STABLECOIN_NOT_ALLOWED")

    if network not in set(agent.allowed_networks):
        check.hard_deny = True
        check.reasons.append("NETWORK_NOT_ALLOWED")

    address = normalize_addr(destination_address)
    blocked = {normalize_addr(a) for a in agent.blocked_destination_addresses}
    allowed = {normalize_addr(a) for a in agent.allowed_destination_addresses}
    if address in blocked:
        check.hard_deny = True
        check.reasons.append("DESTINATION_DENYLISTED")
    if allowed and address not in allowed:
        check.suspicious = True
        check.reasons.append("DESTINATION_NOT_ALLOWLISTED")

    check.context = {
        "asset_type": asset_type,
        "stablecoin_symbol": stablecoin_symbol,
        "network": network,
        "destination_address": address,
    }
    return check

