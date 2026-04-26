from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select

from app.api.v1.schemas.dashboard import (
    ActivityFeedResponse,
    DashboardStatsResponse,
    DashboardNotificationAckRequest,
    DashboardNotificationAckResponse,
    DashboardNotificationListResponse,
)
from app.core.security import AuthContext, verify_agent_auth
from app.db.postgres import get_session
from app.models.agent import Agent
from app.models.dashboard_notification import DashboardNotification
from app.models.spend_audit_log import SpendAuditLog

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


@router.get("/dashboard/agents/{agent_id}/activity", response_model=ActivityFeedResponse)
async def list_agent_activity(
    agent_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    auth_context: AuthContext = Depends(verify_agent_auth),
    session: Session = Depends(get_session),
):
    _ensure_scope(auth_context, agent_id)
    agent = session.exec(select(Agent).where(Agent.agent_id == agent_id)).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    rows = session.exec(
        select(SpendAuditLog)
        .where(SpendAuditLog.agent_id == agent_id)
        .order_by(SpendAuditLog.created_at.desc())
        .limit(limit)
    ).all()
    return {
        "agent_id": agent_id,
        "activity": [
            {
                "request_id": row.request_id,
                "created_at": row.created_at,
                "status": row.status,
                "verdict": row.verdict,
                "vendor_url_or_name": row.vendor_url_or_name,
                "amount_cents": row.amount_cents,
                "currency": row.currency,
                "asset_type": row.asset_type,
                "network": row.network,
                "declared_goal": row.declared_goal,
                "reason": (
                    ((row.semantic_result or {}).get("reason_codes") or [None])[0]
                    if isinstance(row.semantic_result, dict)
                    else None
                ),
                "quantitative_result": row.quantitative_result,
                "policy_result": row.policy_result,
                "semantic_result": row.semantic_result,
            }
            for row in rows
        ],
    }


@router.get("/dashboard/agents/{agent_id}/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    agent_id: str,
    auth_context: AuthContext = Depends(verify_agent_auth),
    session: Session = Depends(get_session),
):
    _ensure_scope(auth_context, agent_id)
    agent = session.exec(select(Agent).where(Agent.agent_id == agent_id)).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_rows = session.exec(
        select(SpendAuditLog)
        .where(SpendAuditLog.agent_id == agent_id)
        .where(SpendAuditLog.created_at >= day_start)
    ).all()

    blocked = len([r for r in today_rows if r.status in {"BLOCKED", "DENIED_BY_HUMAN"}])
    approved = len([r for r in today_rows if r.status in {"APPROVED_EXECUTED", "APPROVED_BY_HUMAN_EXECUTED"}])
    pending_approval = len([r for r in today_rows if r.status == "PENDING_HITL"])
    return {
        "agent_id": agent_id,
        "total_transactions_today": len(today_rows),
        "blocked": blocked,
        "pending_approval": pending_approval,
        "auto_approved": approved,
    }

