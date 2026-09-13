import re

from app.models.agent import Agent
from app.policy.addresses import destination_matches, normalize_destination
from app.policy.currency import currencies_match
from app.policy.vendors import canonical_host, phishing_reason, vendor_allowlisted
from app.policy.verdicts import CheckResult


def _contains_vendor_match(blocked_vendors: list[str], vendor: str) -> bool:
    candidate = vendor.lower().strip()
    candidate_host = canonical_host(candidate)
    candidate_labels = set(candidate_host.split(".")) if candidate_host else set()

    for raw_entry in blocked_vendors:
        entry = raw_entry.lower().strip()
        if not entry:
            continue

        entry_host = canonical_host(entry)
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


def _run_destination_checks(
    check: CheckResult,
    agent: Agent,
    network: str | None,
    destination_address: str | None,
) -> str | None:
    """Destination rules run whenever an address is present, not only for
    stablecoins: a FIAT request carrying an address used to have it stored and
    never compared against either list."""
    address = normalize_destination(destination_address, network)
    if address is None:
        return None

    if any(destination_matches(address, entry, network)
           for entry in agent.blocked_destination_addresses):
        check.hard_deny = True
        check.reasons.append("DESTINATION_DENYLISTED")

    if agent.allowed_destination_addresses and not any(
        destination_matches(address, entry, network)
        for entry in agent.allowed_destination_addresses
    ):
        check.hard_deny = True
        check.reasons.append("DESTINATION_NOT_ALLOWLISTED")

    return address


def run_policy_checks(
    agent: Agent,
    amount_cents: int,
    vendor_url_or_name: str,
    asset_type: str,
    stablecoin_symbol: str | None,
    network: str | None,
    destination_address: str | None,
    currency: str | None = None,
) -> CheckResult:
    check = CheckResult()

    if currency is not None and not currencies_match(currency, agent.currency):
        # The budget counter and every threshold are denominated in the agent's
        # currency; accepting another one would compare unlike amounts.
        check.hard_deny = True
        check.reasons.append("CURRENCY_MISMATCH")

    vendor_blocked = _contains_vendor_match(agent.blocked_vendors, vendor_url_or_name)
    vendor_phishing = phishing_reason(vendor_url_or_name)
    vendor_not_allowlisted = bool(agent.allowed_vendors) and not vendor_allowlisted(
        agent.allowed_vendors, vendor_url_or_name
    )
    if vendor_blocked:
        check.hard_deny = True
        check.reasons.append("VENDOR_MATCHED_BLOCKLIST")
    elif vendor_not_allowlisted:
        # An allowlist is a far stronger control than any heuristic, so it wins
        # over the phishing checks below.
        check.hard_deny = True
        check.reasons.append("VENDOR_NOT_ALLOWLISTED")
    elif vendor_phishing:
        check.hard_deny = True
        check.reasons.append("VENDOR_DOMAIN_PHISHING_PATTERN")
        check.reasons.append(vendor_phishing)
    else:
        check.reasons.append("VENDOR_ALLOWED")

    threshold = (
        agent.per_txn_auto_approve_limit_cents
        if agent.hitl_required_over_cents is None
        else agent.hitl_required_over_cents
    )
    amount_over_threshold = amount_cents > threshold
    if amount_over_threshold:
        # Above the auto-approval ceiling the spend needs a human, not a denial:
        # hard-denying here would return DO_NOT_RETRY and the reviewer would
        # never see the request.
        check.suspicious = True
        check.reasons.append("AMOUNT_OVER_AUTO_APPROVAL_THRESHOLD")
    else:
        check.reasons.append("AMOUNT_WITHIN_AUTO_APPROVAL_THRESHOLD")

    if asset_type == "STABLECOIN":
        if stablecoin_symbol not in set(agent.allowed_stablecoins):
            check.hard_deny = True
            check.reasons.append("STABLECOIN_NOT_ALLOWED")
        if network not in set(agent.allowed_networks):
            check.hard_deny = True
            check.reasons.append("NETWORK_NOT_ALLOWED")
        if not (destination_address or "").strip():
            check.hard_deny = True
            check.reasons.append("DESTINATION_ADDRESS_MISSING")

    address = _run_destination_checks(check, agent, network, destination_address)

    check.context = {
        "vendor_blocked": vendor_blocked,
        "vendor_host": canonical_host(vendor_url_or_name),
        "vendor_phishing_reason": vendor_phishing,
        "amount_over_threshold": amount_over_threshold,
        "threshold_cents": threshold,
        "currency": (currency or agent.currency).strip().upper(),
        "stablecoin": {
            "asset_type": asset_type,
            "stablecoin_symbol": stablecoin_symbol,
            "network": network,
            "destination_address": address,
        },
    }
    return check
