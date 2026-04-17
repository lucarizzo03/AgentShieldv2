import pytest

from app.models.agent import Agent
from app.policy.checks.policy_db import run_policy_checks
from app.services.payment.stablecoin_policy import validate_stablecoin_policy


def _agent() -> Agent:
    return Agent(
        agent_id="agent_u_1",
        blocked_vendors=["badvendor"],
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
        vendor_url_or_name="https://badvendor.example",
        asset_type="STABLECOIN",
        stablecoin_symbol="USDC",
        network="base",
        destination_address="0xabc1234567890000",
    )
    assert result.hard_deny is True
    assert "VENDOR_MATCHED_BLOCKLIST" in result.reasons


def test_stablecoin_destination_not_allowlisted_is_suspicious() -> None:
    agent = _agent()
    result = validate_stablecoin_policy(
        agent=agent,
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
    result = validate_stablecoin_policy(
        agent=agent,
        asset_type="STABLECOIN",
        stablecoin_symbol=symbol,
        network=network,
        destination_address="0xabc1234567890000",
    )
    assert result.hard_deny is True

