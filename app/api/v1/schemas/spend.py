from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class SpendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=3, max_length=128)
    declared_goal: str = Field(min_length=3, max_length=2000)
    amount_cents: int = Field(ge=1, le=100_000_000)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    vendor_url_or_name: str = Field(min_length=2, max_length=512)
    item_description: str = Field(min_length=2, max_length=4000)
    asset_type: Literal["STABLECOIN", "FIAT"]
    stablecoin_symbol: Literal["USDC", "USDT"] | None = None
    network: Literal["ethereum", "base", "solana", "polygon", "arbitrum"] | None = None
    destination_address: str | None = Field(default=None, min_length=16, max_length=128)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=128)
    agent_callback_url: HttpUrl | None = None

    @model_validator(mode="after")
    def validate_stablecoin_fields(self) -> "SpendRequest":
        if self.asset_type == "STABLECOIN":
            required_fields = [self.stablecoin_symbol, self.network, self.destination_address]
            if any(value is None for value in required_fields):
                raise ValueError(
                    "stablecoin_symbol, network, and destination_address are required for STABLECOIN"
                )
        return self


class PaymentExecutionResult(BaseModel):
    provider: str
    provider_txn_id: str
    asset_type: Literal["STABLECOIN", "FIAT"]
    stablecoin_symbol: str | None = None
    network: str | None = None
    destination_address: str | None = None
    onchain_tx_hash: str | None = None
    executed_at: datetime


class SpendApprovedResponse(BaseModel):
    request_id: str
    status: Literal["APPROVED_EXECUTED"]
    verdict: Literal["SAFE"]
    approved_amount_cents: int
    currency: str
    payment: PaymentExecutionResult
    reasons: list[str]


class SpendBlockedResponse(BaseModel):
    request_id: str
    status: Literal["BLOCKED"]
    verdict: Literal["MALICIOUS"]
    block_code: str
    reasons: list[str]
    next_action: Literal["DO_NOT_RETRY"]


class HitlStatePayload(BaseModel):
    state: Literal["WAITING_HUMAN_TEXT_RESPONSE"]
    channel: Literal["sms", "dashboard"]
    requested_at: datetime
    expires_at: datetime


class SpendPendingResponse(BaseModel):
    request_id: str
    status: Literal["PENDING_HITL"]
    verdict: Literal["SUSPICIOUS"]
    hitl: HitlStatePayload
    reasons: list[str]
    next_action: Literal["AGENT_MUST_WAIT"]

