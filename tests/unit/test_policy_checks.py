import pytest

from app.models.agent import Agent
from app.policy.checks.policy_db import run_policy_checks


def _agent() -> Agent:
    return Agent(
        agent_id="agent_u_1",
        blocked_vendors=["badvendor.com"],
        allowed_stablecoins=["USDC"],
        allowed_networks=["base"],
        allowed_destination_addresses=["0xabc1234567890000"],
        blocked_destination_addresses=["0xdeadbeefdeadbeef"],
    )


def test_policy_vendor_blocklist_hard_deny() -> None:
    agent = _agent()
    result = run_policy_checks(
        agent=agent,
        amount_cents=500,
        vendor_url_or_name="https://checkout.badvendor.com/portal",
        asset_type="STABLECOIN",
        stablecoin_symbol="USDC",
        network="base",
        destination_address="0xabc1234567890000",
    )
    assert result.hard_deny is True
    assert "VENDOR_MATCHED_BLOCKLIST" in result.reasons


def test_policy_vendor_label_blocklist_hard_deny() -> None:
    agent = _agent()
    agent.blocked_vendors = ["badvendor"]
    result = run_policy_checks(
        agent=agent,
        amount_cents=500,
        vendor_url_or_name="https://badvendor.example",
        asset_type="STABLECOIN",
        stablecoin_symbol="USDC",
        network="base",
        destination_address="0xabc1234567890000",
    )
    assert result.hard_deny is True
    assert "VENDOR_MATCHED_BLOCKLIST" in result.reasons


def test_policy_vendor_does_not_block_on_broad_substring() -> None:
    agent = _agent()
    agent.blocked_vendors = ["pay"]
    result = run_policy_checks(
        agent=agent,
        amount_cents=500,
        vendor_url_or_name="https://abstract-exchange-rates.mpp.paywithlocus.com/abstract-exchange-rates/live",
        asset_type="STABLECOIN",
        stablecoin_symbol="USDC",
        network="base",
        destination_address="0xabc1234567890000",
    )
    assert result.hard_deny is False
    assert "VENDOR_MATCHED_BLOCKLIST" not in result.reasons
    assert "VENDOR_ALLOWED" in result.reasons


def test_stablecoin_destination_not_allowlisted_is_suspicious() -> None:
    agent = _agent()
    result = run_policy_checks(
        agent=agent,
        amount_cents=500,
        vendor_url_or_name="legit.com",
        asset_type="STABLECOIN",
        stablecoin_symbol="USDC",
        network="base",
        destination_address="0x1111111111111111",
    )
    assert result.suspicious is True
    assert "DESTINATION_NOT_ALLOWLISTED" in result.reasons


@pytest.mark.parametrize("symbol,network", [("USDT", "base"), ("USDC", "ethereum")])
def test_stablecoin_chain_token_policy_hard_deny(symbol: str, network: str) -> None:
    agent = _agent()
    result = run_policy_checks(
        agent=agent,
        amount_cents=500,
        vendor_url_or_name="legit.com",
        asset_type="STABLECOIN",
        stablecoin_symbol=symbol,
        network=network,
        destination_address="0xabc1234567890000",
    )
    assert result.hard_deny is True
