from datetime import datetime, timezone
from uuid import uuid4

from app.api.v1.schemas.spend import SpendRequest
from app.services.payment.adapter_base import PaymentAdapter


class TempoAdapter(PaymentAdapter):
    async def execute(self, request_id: str, spend_request: SpendRequest) -> dict:
        provider_txn_id = f"tp_txn_{uuid4().hex[:12]}"
        return {
            "provider": "tempo",
            "provider_txn_id": provider_txn_id,
            "asset_type": spend_request.asset_type,
            "stablecoin_symbol": spend_request.stablecoin_symbol,
            "network": spend_request.network,
            "destination_address": spend_request.destination_address,
            "onchain_tx_hash": f"0x{uuid4().hex}{uuid4().hex[:8]}",
            "executed_at": datetime.now(timezone.utc),
        }

