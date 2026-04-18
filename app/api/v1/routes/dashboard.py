from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select

from app.api.v1.schemas.dashboard import (
    DashboardNotificationAckRequest,
    DashboardNotificationAckResponse,
    DashboardNotificationListResponse,
)
from app.core.security import AuthContext, verify_agent_auth
from app.db.postgres import get_session
from app.models.agent import Agent
from app.models.dashboard_notification import DashboardNotification

router = APIRouter(tags=["dashboard"])


def _ensure_scope(auth_context: AuthContext, agent_id: str) -> None:
    if auth_context.agent_id and auth_context.agent_id != agent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated agent_id does not match requested agent_id",
        )


@router.get("/dashboard/agents/{agent_id}/notifications", response_model=DashboardNotificationListResponse)
async def list_dashboard_notifications(
    agent_id: str,
    notification_status: str = Query(default="OPEN", alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    auth_context: AuthContext = Depends(verify_agent_auth),
    session: Session = Depends(get_session),
):
    _ensure_scope(auth_context, agent_id)
    agent = session.exec(select(Agent).where(Agent.agent_id == agent_id)).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    rows = session.exec(
        select(DashboardNotification)
        .where(DashboardNotification.agent_id == agent_id)
        .where(DashboardNotification.status == notification_status.upper())
        .order_by(DashboardNotification.created_at.desc())
        .limit(limit)
    ).all()
    return {"agent_id": agent_id, "notifications": rows}


@router.patch(
    "/dashboard/agents/{agent_id}/notifications/{notification_id}",
    response_model=DashboardNotificationAckResponse,
)
async def update_dashboard_notification(
    agent_id: str,
    notification_id: UUID,
    payload: DashboardNotificationAckRequest,
    auth_context: AuthContext = Depends(verify_agent_auth),
    session: Session = Depends(get_session),
):
    _ensure_scope(auth_context, agent_id)
    notification = session.exec(select(DashboardNotification).where(DashboardNotification.id == notification_id)).first()
    if not notification or notification.agent_id != agent_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")

    if notification.status in {"RESOLVED", "DISMISSED"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Notification already finalized")

    now = datetime.now(timezone.utc)
    notification.status = "ACKED" if payload.action == "ACK" else "DISMISSED"
    notification.acknowledged_by = auth_context.principal_id
    notification.acknowledged_at = now
    notification.updated_at = now
    session.add(notification)
    session.commit()

    return {
        "notification_id": notification.id,
        "status": notification.status,
        "acknowledged_by": notification.acknowledged_by,
        "acknowledged_at": notification.acknowledged_at,
    }

