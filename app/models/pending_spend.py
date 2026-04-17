from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class PendingSpend(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    request_id: str = Field(index=True, unique=True, max_length=64)
    agent_id: str = Field(index=True, max_length=128)
    payload_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    verdict_snapshot: dict = Field(default_factory=dict, sa_column=Column(JSON))
    state: str = Field(default="WAITING_HUMAN", max_length=32)
    hitl_channel: str = Field(default="sms", max_length=16)
    hitl_contact: str | None = Field(default=None, max_length=128)
    expires_at: datetime = Field(index=True)
    resolved_at: datetime | None = None
    resolver_id: str | None = Field(default=None, max_length=128)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

