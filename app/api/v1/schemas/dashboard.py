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


class ActivityItem(BaseModel):
    request_id: str
    created_at: datetime
    status: str
    verdict: str
    vendor_url_or_name: str
    amount_cents: int
    currency: str
    asset_type: str
    network: str | None = None
    declared_goal: str
    reason: str | None = None
    quantitative_result: dict
    policy_result: dict
    semantic_result: dict


class ActivityFeedResponse(BaseModel):
    agent_id: str
    activity: list[ActivityItem]


class DashboardStatsResponse(BaseModel):
    agent_id: str
    total_transactions_today: int
    blocked: int
    pending_approval: int
    auto_approved: int

