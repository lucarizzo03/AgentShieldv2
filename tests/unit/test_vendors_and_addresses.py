from app.models.agent import Agent
from app.policy.addresses import destination_matches, normalize_destination
from app.policy.checks.policy_db import run_policy_checks
from app.policy.vendors import canonical_host, phishing_reason, vendor_allowlisted

_EVM = "0x742d35cc6634c0532925a3b8d4c9a6b52e7a1f11"
_SOL = "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin"


def _agent() -> Agent:
    return Agent(agent_id="agent_v_1", allowed_networks=["base", "solana"])


def test_userinfo_url_resolves_to_the_real_host() -> None:
    assert canonical_host("https://delta.com@evil.com/pay") == "evil.com"
    assert phishing_reason("https://delta.com@evil.com/pay") == "VENDOR_URL_EMBEDS_USERINFO"


def test_free_text_vendor_names_have_no_host_and_are_not_flagged() -> None:
    assert canonical_host("Delta Air Lines") is None
    assert phishing_reason("Delta Air Lines") is None


def test_ip_literal_and_punycode_hosts_are_flagged() -> None:
    assert phishing_reason("http://203.0.113.9/checkout") == "VENDOR_HOST_IS_IP_LITERAL"
    assert phishing_reason("https://xn--dlta-0qa.com") == "VENDOR_HOST_PUNYCODE"


def test_brand_lookalike_is_flagged_but_the_brand_itself_is_not() -> None:
    assert phishing_reason("https://delt.com/pay") == "VENDOR_HOST_BRAND_LOOKALIKE"
    assert phishing_reason("https://www.delta.com/checkout") is None


def test_allowlist_matches_host_and_subdomains_only() -> None:
    allowed = ["delta.com", "Acme Catering"]
    assert vendor_allowlisted(allowed, "https://checkout.delta.com/pay") is True
    assert vendor_allowlisted(allowed, "https://delta.com.evil.com") is False
    assert vendor_allowlisted(allowed, "acme catering") is True


def test_vendor_not_on_allowlist_is_hard_denied() -> None:
    agent = _agent()
    agent.allowed_vendors = ["delta.com"]
    result = run_policy_checks(
        agent=agent,
        amount_cents=500,
        vendor_url_or_name="https://united.com/book",
        asset_type="FIAT",
        stablecoin_symbol=None,
        network=None,
        destination_address=None,
    )
    assert result.hard_deny is True
    assert "VENDOR_NOT_ALLOWLISTED" in result.reasons


def test_evm_addresses_case_fold_and_solana_addresses_do_not() -> None:
    assert normalize_destination(_EVM.upper().replace("0X", "0x"), "base") == _EVM
    assert normalize_destination(_SOL, "solana") == _SOL
    assert destination_matches(_SOL, _SOL.lower(), "solana") is False
    assert destination_matches(_EVM, _EVM.upper().replace("0X", "0x"), "base") is True


def test_solana_denylist_cannot_be_evaded_by_recasing() -> None:
    agent = _agent()
    agent.blocked_destination_addresses = [_SOL]
    denied = run_policy_checks(
        agent=agent,
        amount_cents=500,
        vendor_url_or_name="legit.com",
        asset_type="STABLECOIN",
        stablecoin_symbol="USDC",
        network="solana",
        destination_address=_SOL,
    )
    assert "DESTINATION_DENYLISTED" in denied.reasons


def test_fiat_destination_is_checked_against_the_denylist() -> None:
    agent = _agent()
    agent.blocked_destination_addresses = ["DE89370400440532013000"]
    result = run_policy_checks(
        agent=agent,
        amount_cents=500,
        vendor_url_or_name="legit.com",
        asset_type="FIAT",
        stablecoin_symbol=None,
        network=None,
        destination_address="de89370400440532013000",
    )
    assert result.hard_deny is True
    assert "DESTINATION_DENYLISTED" in result.reasons
