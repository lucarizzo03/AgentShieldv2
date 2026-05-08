from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class SpendAuditLog(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    request_id: str = Field(index=True, max_length=64)
    agent_id: str = Field(index=True, max_length=128)
    declared_goal: str
    amount_cents: int
    currency: str = Field(max_length=3)
    asset_type: str = Field(default="STABLECOIN", max_length=16)
    stablecoin_symbol: str | None = Field(default=None, max_length=16)
    network: str | None = Field(default=None, max_length=32)
    destination_address: str | None = Field(default=None, max_length=128)
    vendor_url_or_name: str
    item_description: str
    quantitative_result: dict = Field(default_factory=dict, sa_column=Column(JSON))
    policy_result: dict = Field(default_factory=dict, sa_column=Column(JSON))
    semantic_result: dict = Field(default_factory=dict, sa_column=Column(JSON))
    goal_drift_result: dict = Field(default_factory=dict, sa_column=Column(JSON))
    verdict: str = Field(max_length=16)
    status: str = Field(max_length=48)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

