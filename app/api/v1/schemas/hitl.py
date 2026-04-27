from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HitlResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["APPROVE", "DENY"]
    resolver_id: str = Field(min_length=2, max_length=128)
    channel: Literal["dashboard", "sms", "email"]
    resolution_note: str | None = Field(default=None, max_length=1000)
    provider_message_id: str | None = Field(default=None, max_length=128)


class HitlResolveResponsePayment(BaseModel):
    executed: bool
    provider: str | None = None
    provider_txn_id: str | None = None


class HitlResolveResponse(BaseModel):
    request_id: str
    status: Literal["RESOLVED"]
    decision: Literal["APPROVE", "DENY"]
    resolved_at: datetime
    payment: HitlResolveResponsePayment

