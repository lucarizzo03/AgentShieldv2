import re
from urllib.parse import urlparse

from app.models.agent import Agent
from app.policy.verdicts import CheckResult


def _contains_vendor_match(blocked_vendors: list[str], vendor: str) -> bool:
    candidate = vendor.lower().strip()
    candidate_host = _extract_hostname(candidate)
    candidate_labels = set(candidate_host.split(".")) if candidate_host else set()

    for raw_entry in blocked_vendors:
        entry = raw_entry.lower().strip()
        if not entry:
            continue

        entry_host = _extract_hostname(entry)
        if entry_host and candidate_host:
            # Domain-like entries are matched as exact host or subdomain suffix.
            if candidate_host == entry_host or candidate_host.endswith(f".{entry_host}"):
                return True
            continue

        if candidate_host and entry in candidate_labels:
            # Allow blocking by a full DNS label (e.g. "badvendor"), but avoid
            # broad substring matches (e.g. "pay" should not match "paywithlocus").
            return True

        if candidate_host:
            # For URL/domain candidates, do not fall back to free-text matching
            # across the full URL/path because broad terms (e.g. "exchange")
            # can create false positives on legitimate endpoints.
            continue

        if candidate == entry:
            return True

        if re.search(rf"\b{re.escape(entry)}\b", candidate):
            return True

    return False


def _extract_hostname(value: str) -> str | None:
    raw = value.strip().lower()
    if not raw:
        return None

    with_scheme = raw if "://" in raw else f"https://{raw}"
    parsed = urlparse(with_scheme)
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return None
    if re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", host) is None:
        return None
    return host


def _is_phishing_vendor(vendor: str) -> bool:
    if re.search(r'/:[a-zA-Z]', vendor):
        return True
    match = re.match(r'https?://([^/]+)', vendor)
    hostname = match.group(1) if match else vendor.split('/')[0]
    subdomain = hostname.split('.')[0]
    if len(subdomain) > 30:
        return True
    return False


def _normalize_addr(address: str | None) -> str:
    return (address or "").strip().lower()


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
    elif _is_phishing_vendor(vendor_url_or_name):
        check.hard_deny = True
        check.reasons.append("VENDOR_DOMAIN_PHISHING_PATTERN")
    else:
        check.reasons.append("VENDOR_ALLOWED")

    threshold = (
        agent.per_txn_auto_approve_limit_cents
        if agent.hitl_required_over_cents is None
        else agent.hitl_required_over_cents
    )
    amount_over_threshold = amount_cents > threshold
    if amount_over_threshold:
        check.suspicious = True
        check.reasons.append("AMOUNT_OVER_AUTO_APPROVAL_THRESHOLD")
    else:
        check.reasons.append("AMOUNT_WITHIN_AUTO_APPROVAL_THRESHOLD")

    stablecoin_context: dict = {"asset_type": asset_type}
    if asset_type == "STABLECOIN":
        if stablecoin_symbol not in set(agent.allowed_stablecoins):
            check.hard_deny = True
            check.reasons.append("STABLECOIN_NOT_ALLOWED")
        if network not in set(agent.allowed_networks):
            check.hard_deny = True
            check.reasons.append("NETWORK_NOT_ALLOWED")
        address = _normalize_addr(destination_address)
        blocked = {_normalize_addr(a) for a in agent.blocked_destination_addresses}
        allowed = {_normalize_addr(a) for a in agent.allowed_destination_addresses}
        if not address:
            check.suspicious = True
            check.reasons.append("DESTINATION_ADDRESS_MISSING")
        else:
            if address in blocked:
                check.hard_deny = True
                check.reasons.append("DESTINATION_DENYLISTED")
            if allowed and address not in allowed:
                check.suspicious = True
                check.reasons.append("DESTINATION_NOT_ALLOWLISTED")
        stablecoin_context = {
            "asset_type": asset_type,
            "stablecoin_symbol": stablecoin_symbol,
            "network": network,
            "destination_address": address or None,
        }

    check.context = {
        "vendor_blocked": vendor_blocked,
        "amount_over_threshold": amount_over_threshold,
        "threshold_cents": threshold,
        "stablecoin": stablecoin_context,
    }
    return check

