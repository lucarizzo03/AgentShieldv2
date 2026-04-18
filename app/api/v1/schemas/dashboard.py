from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DashboardNotificationItem(BaseModel):
    id: UUID
    request_id: str
    agent_id: str
    category: str
    priority: Literal["NORMAL", "HIGH"]
    status: Literal["OPEN", "ACKED", "RESOLVED", "DISMISSED"]
    summary: str
    payload_json: dict
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DashboardNotificationListResponse(BaseModel):
    agent_id: str
    notifications: list[DashboardNotificationItem]


class DashboardNotificationAckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["ACK", "DISMISS"] = Field(default="ACK")


class DashboardNotificationAckResponse(BaseModel):
    notification_id: UUID
    status: Literal["ACKED", "DISMISSED"]
    acknowledged_by: str
    acknowledged_at: datetime

