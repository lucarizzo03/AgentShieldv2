from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.schemas.dashboard import (
    ActivityFeedResponse,
    DashboardStatsResponse,
    DashboardNotificationAckRequest,
    DashboardNotificationAckResponse,
    DashboardNotificationListResponse,
)
from app.core.security import UserAuthContext, verify_user_auth
from app.db.postgres import get_session
from app.models.agent import Agent
from app.models.dashboard_notification import DashboardNotification
from app.models.pending_spend import PendingSpend
from app.models.spend_audit_log import SpendAuditLog
from app.services.user_identity import get_or_create_user

router = APIRouter(tags=["dashboard"])


async def _load_owned_agent(session: AsyncSession, *, auth_context: UserAuthContext, owner_user_id, agent_id: str) -> Agent:
    query = select(Agent).where(Agent.agent_id == agent_id)
    if auth_context.agent_id:
        if auth_context.agent_id != agent_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    else:
        query = query.where(Agent.owner_user_id == owner_user_id)
    agent = (await session.exec(query)).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return agent


def _normalize_optional_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def _scoped_rows(
    session: AsyncSession,
    *,
    agent_id: str,
    count_mode: str,
    start_at: datetime | None,
    end_at: datetime | None,
) -> list[SpendAuditLog]:
    query = select(SpendAuditLog).where(SpendAuditLog.agent_id == agent_id)
    if count_mode == "today_utc":
        day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        query = query.where(SpendAuditLog.created_at >= day_start)
    else:
        if start_at is not None:
            query = query.where(SpendAuditLog.created_at >= start_at)
        if end_at is not None:
            query = query.where(SpendAuditLog.created_at <= end_at)

    return (await session.exec(query.order_by(SpendAuditLog.created_at.desc()))).all()


async def _latest_unique_transactions(
    session: AsyncSession,
    *,
    agent_id: str,
    count_mode: str,
    start_at: datetime | None,
    end_at: datetime | None,
) -> list[SpendAuditLog]:
    today_rows = await _scoped_rows(
        session,
        agent_id=agent_id,
        count_mode=count_mode,
        start_at=start_at,
        end_at=end_at,
    )
    latest: dict[str, SpendAuditLog] = {}
    for row in today_rows:
        if row.request_id not in latest or row.created_at > latest[row.request_id].created_at:
            latest[row.request_id] = row
    return sorted(latest.values(), key=lambda row: row.created_at, reverse=True)


async def _activity_rows(
    session: AsyncSession,
    *,
    agent_id: str,
    count_mode: str,
    start_at: datetime | None,
    end_at: datetime | None,
) -> list[SpendAuditLog]:
    today_rows = await _scoped_rows(
        session,
        agent_id=agent_id,
        count_mode=count_mode,
        start_at=start_at,
        end_at=end_at,
    )
    latest_non_replay: dict[str, SpendAuditLog] = {}
    replay_rows: list[SpendAuditLog] = []

    for row in today_rows:
        is_replay = bool((row.quantitative_result or {}).get("idempotency_replay", False))
        if is_replay:
            replay_rows.append(row)
            continue
        if row.request_id not in latest_non_replay:
            latest_non_replay[row.request_id] = row

    merged = [*latest_non_replay.values(), *replay_rows]
    return sorted(merged, key=lambda row: row.created_at, reverse=True)


@router.get("/dashboard/agents/{agent_id}/notifications", response_model=DashboardNotificationListResponse)
async def list_dashboard_notifications(
    agent_id: str,
    notification_status: str = Query(default="OPEN", alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    auth_context: UserAuthContext = Depends(verify_user_auth),
    session: AsyncSession = Depends(get_session),
):
    user = None if auth_context.agent_id else await get_or_create_user(session, auth_context)
    await _load_owned_agent(session, auth_context=auth_context, owner_user_id=user.id if user else None, agent_id=agent_id)

    rows = (await session.exec(
        select(DashboardNotification)
        .where(DashboardNotification.agent_id == agent_id)
        .where(DashboardNotification.status == notification_status.upper())
        .order_by(DashboardNotification.created_at.desc())
        .limit(limit)
    )).all()

    now = datetime.now(timezone.utc)
    active = []
    for n in rows:
        expires_at_str = (n.payload_json or {}).get("expires_at")
        expired = False
        if expires_at_str:
            try:
                exp = datetime.fromisoformat(expires_at_str)
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                expired = exp < now
            except (ValueError, TypeError):
                pass

        if expired:
            n.status = "DISMISSED"
            n.updated_at = now
            session.add(n)
            audit = (await session.exec(
                select(SpendAuditLog)
                .where(SpendAuditLog.request_id == n.request_id)
                .order_by(SpendAuditLog.created_at.desc())
            )).first()
            if audit and audit.status == "PENDING_HITL":
                session.add(SpendAuditLog(
                    request_id=audit.request_id,
                    agent_id=audit.agent_id,
                    declared_goal=audit.declared_goal,
                    amount_cents=audit.amount_cents,
                    currency=audit.currency,
                    asset_type=audit.asset_type,
                    stablecoin_symbol=audit.stablecoin_symbol,
                    network=audit.network,
                    destination_address=audit.destination_address,
                    vendor_url_or_name=audit.vendor_url_or_name,
                    item_description=audit.item_description,
                    quantitative_result=audit.quantitative_result,
                    policy_result=audit.policy_result,
                    semantic_result=audit.semantic_result,
                    goal_drift_result=audit.goal_drift_result,
                    verdict=audit.verdict,
                    status="EXPIRED",
                ))
            pending = (await session.exec(
                select(PendingSpend).where(PendingSpend.request_id == n.request_id)
            )).first()
            if pending and pending.state == "WAITING_HUMAN":
                pending.state = "EXPIRED"
                session.add(pending)
        else:
            active.append(n)

    if len(active) < len(rows):
        await session.commit()

    return {"agent_id": agent_id, "notifications": active}


@router.patch(
    "/dashboard/agents/{agent_id}/notifications/{notification_id}",
    response_model=DashboardNotificationAckResponse,
)
async def update_dashboard_notification(
    agent_id: str,
    notification_id: UUID,
    payload: DashboardNotificationAckRequest,
    auth_context: UserAuthContext = Depends(verify_user_auth),
    session: AsyncSession = Depends(get_session),
):
    user = None if auth_context.agent_id else await get_or_create_user(session, auth_context)
    await _load_owned_agent(session, auth_context=auth_context, owner_user_id=user.id if user else None, agent_id=agent_id)
    notification = (await session.exec(select(DashboardNotification).where(DashboardNotification.id == notification_id))).first()
    if not notification or notification.agent_id != agent_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")

    if notification.status in {"RESOLVED", "DISMISSED"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Notification already finalized")

    now = datetime.now(timezone.utc)
    notification.status = "ACKED" if payload.action == "ACK" else "DISMISSED"
    notification.acknowledged_by = auth_context.email or auth_context.sub
    notification.acknowledged_at = now
    notification.updated_at = now
    session.add(notification)
    await session.commit()

    return {
        "notification_id": notification.id,
        "status": notification.status,
        "acknowledged_by": notification.acknowledged_by,
        "acknowledged_at": notification.acknowledged_at,
    }


@router.get("/dashboard/agents/{agent_id}/activity", response_model=ActivityFeedResponse)
async def list_agent_activity(
    agent_id: str,
    limit: int = Query(default=500, ge=1, le=2000),
    scope: str = Query(default="all_time", pattern="^(all_time|today_utc)$"),
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    auth_context: UserAuthContext = Depends(verify_user_auth),
    session: AsyncSession = Depends(get_session),
):
    user = None if auth_context.agent_id else await get_or_create_user(session, auth_context)
    await _load_owned_agent(session, auth_context=auth_context, owner_user_id=user.id if user else None, agent_id=agent_id)

    start = _normalize_optional_utc(start_at)
    end = _normalize_optional_utc(end_at)
    if start and end and end < start:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="end_at must be >= start_at")

    count_mode = "range_utc" if (start or end) else scope
    latest_today = await _latest_unique_transactions(
        session,
        agent_id=agent_id,
        count_mode=count_mode,
        start_at=start,
        end_at=end,
    )
    rows = (await _activity_rows(
        session,
        agent_id=agent_id,
        count_mode=count_mode,
        start_at=start,
        end_at=end,
    ))[:limit]
    return {
        "agent_id": agent_id,
        "total_transactions_today": len(latest_today),
        "count_mode": count_mode,
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
                    lambda rc: rc.get("code", str(rc)) if isinstance(rc, dict) else rc
                )(((row.semantic_result or {}).get("reason_codes") or [None])[0])
                if isinstance(row.semantic_result, dict)
                else None,
                "quantitative_result": row.quantitative_result or {},
                "policy_result": row.policy_result or {},
                "semantic_result": row.semantic_result or {},
                "goal_drift_result": row.goal_drift_result or {},
                "idempotency_replay": bool((row.quantitative_result or {}).get("idempotency_replay", False)),
            }
            for row in rows
        ],
    }


@router.get("/dashboard/agents/{agent_id}/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    agent_id: str,
    scope: str = Query(default="all_time", pattern="^(all_time|today_utc)$"),
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
    auth_context: UserAuthContext = Depends(verify_user_auth),
    session: AsyncSession = Depends(get_session),
):
    user = None if auth_context.agent_id else await get_or_create_user(session, auth_context)
    await _load_owned_agent(session, auth_context=auth_context, owner_user_id=user.id if user else None, agent_id=agent_id)

    start = _normalize_optional_utc(start_at)
    end = _normalize_optional_utc(end_at)
    if start and end and end < start:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="end_at must be >= start_at")

    count_mode = "range_utc" if (start or end) else scope
    unique = await _latest_unique_transactions(
        session,
        agent_id=agent_id,
        count_mode=count_mode,
        start_at=start,
        end_at=end,
    )

    blocked = len([r for r in unique if r.status in {"BLOCKED", "DENIED_BY_HUMAN"}])
    approved = len([r for r in unique if r.status in {"APPROVED_EXECUTED", "APPROVED_BY_HUMAN_EXECUTED"}])
    pending_approval = len([r for r in unique if r.status == "PENDING_HITL"])
    return {
        "agent_id": agent_id,
        "total_transactions_today": len(unique),
        "blocked": blocked,
        "pending_approval": pending_approval,
        "auto_approved": approved,
    }

