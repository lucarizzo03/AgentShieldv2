from app.api.v1.schemas.hitl import HitlResolveRequest
from app.api.v1.schemas.spend import SpendRequest


def test_spend_request_contract_fields() -> None:
    payload = SpendRequest(
        agent_id="agent_contract",
        declared_goal="Launch product website",
        amount_cents=2500,
        currency="USD",
        vendor_url_or_name="tempo",
        item_description="Stablecoin payment for service",
        asset_type="STABLECOIN",
        stablecoin_symbol="USDC",
        network="base",
        destination_address="0x1234567890abcdef",
    )
    data = payload.model_dump()
    assert "agent_id" in data
    assert "declared_goal" in data
    assert data["asset_type"] == "STABLECOIN"


def test_hitl_resolve_contract_fields() -> None:
    payload = HitlResolveRequest(decision="APPROVE", resolver_id="human_1", channel="sms")
    data = payload.model_dump()
    assert data["decision"] == "APPROVE"
    assert data["channel"] == "sms"

