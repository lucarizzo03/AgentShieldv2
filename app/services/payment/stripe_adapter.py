from datetime import datetime, timezone
from uuid import uuid4

from app.api.v1.schemas.spend import SpendRequest
from app.services.payment.adapter_base import PaymentAdapter


class StripeAdapter(PaymentAdapter):
    async def execute(self, request_id: str, spend_request: SpendRequest) -> dict:
        return {
            "provider": "stripe",
            "provider_txn_id": f"st_txn_{uuid4().hex[:12]}",
            "asset_type": spend_request.asset_type,
            "stablecoin_symbol": spend_request.stablecoin_symbol,
            "network": spend_request.network,
            "destination_address": spend_request.destination_address,
            "onchain_tx_hash": None,
            "executed_at": datetime.now(timezone.utc),
        }

