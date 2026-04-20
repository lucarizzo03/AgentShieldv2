from datetime import datetime, timezone
from secrets import token_urlsafe
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.api.v1.schemas.onboarding import (
    OnboardingBootstrapRequest,
    OnboardingBootstrapResponse,
    OnboardingChecklistResponse,
)
from app.core.security import AuthContext, verify_agent_auth
from app.db.postgres import get_session
from app.models.agent import Agent
from app.models.dashboard_notification import DashboardNotification
from app.models.spend_audit_log import SpendAuditLog

router = APIRouter(tags=["onboarding"])


@router.post("/onboarding/bootstrap", response_model=OnboardingBootstrapResponse)
async def bootstrap_onboarding(payload: OnboardingBootstrapRequest, session: Session = Depends(get_session)):
    existing = session.exec(select(Agent).where(Agent.display_name == payload.agent_name)).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent name already exists. Choose a different name.",
        )

    now = datetime.now(timezone.utc)
    agent_id = f"agt_{uuid4().hex[:18]}"
    hmac_secret = f"sk_live_{token_urlsafe(18)}"
    agent = Agent(
        agent_id=agent_id,
        display_name=payload.agent_name,
        daily_budget_limit_cents=payload.daily_spend_limit_usd * 100,
        per_txn_auto_approve_limit_cents=payload.per_transaction_limit_usd * 100,
        hitl_required_over_cents=payload.auto_approve_under_usd * 100,
        blocked_vendors=payload.blocked_vendors,
        allowed_networks=payload.allowed_networks or ["base"],
        allowed_stablecoins=payload.allowed_tokens or ["USDC"],
        currency="USD",
        hmac_secret=hmac_secret,
        hmac_secret_rotated_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(agent)
    session.commit()

    quickstart_curl = (
        "curl -X POST http://127.0.0.1:8000/v1/spend-request "
        f"-H 'x-agent-key: local-dev-key' -H 'x-agent-id: {agent_id}' "
        "-H 'Content-Type: application/json' "
        f"-d '{{\"agent_id\":\"{agent_id}\",\"declared_goal\":\"Book travel\","
        "\"amount_cents\":4900,\"currency\":\"USD\",\"vendor_url_or_name\":\"Delta Airlines\","
        "\"item_description\":\"Flight booking\",\"asset_type\":\"STABLECOIN\","
        "\"stablecoin_symbol\":\"USDC\",\"network\":\"base\","
        "\"destination_address\":\"0x742d35Cc6634C0532925a3b8D4C9A6b52E7A1f1\","
        "\"idempotency_key\":\"quickstart-001\"}}'"
    )
    return {
        "user_name": payload.user_name,
        "email": payload.email,
        "agent_id": agent_id,
        "display_name": payload.agent_name,
        "hmac_secret": hmac_secret,
        "next_steps": [
            "Send one SAFE test request",
            "Send one SUSPICIOUS test request",
            "Approve or deny the pending HITL request from the dashboard",
        ],
        "quickstart_curl": quickstart_curl,
    }


@router.get("/onboarding/agents/{agent_id}/checklist", response_model=OnboardingChecklistResponse)
async def get_onboarding_checklist(
    agent_id: str,
    auth_context: AuthContext = Depends(verify_agent_auth),
    session: Session = Depends(get_session),
):
    if auth_context.agent_id and auth_context.agent_id != agent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated agent_id does not match requested agent_id",
        )

    agent = session.exec(select(Agent).where(Agent.agent_id == agent_id)).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    logs = session.exec(select(SpendAuditLog).where(SpendAuditLog.agent_id == agent_id)).all()
    pending_open_count = len(
        session.exec(
            select(DashboardNotification)
            .where(DashboardNotification.agent_id == agent_id)
            .where(DashboardNotification.status == "OPEN")
        ).all()
    )

    first_safe_executed = any(row.status == "APPROVED_EXECUTED" for row in logs)
    pending_hitl_created = any(row.status == "PENDING_HITL" for row in logs) or pending_open_count > 0
    human_resolution_done = any(
        row.status in {"APPROVED_BY_HUMAN_EXECUTED", "DENIED_BY_HUMAN"} for row in logs
    )
    return {
        "agent_id": agent_id,
        "agent_created": True,
        "first_safe_executed": first_safe_executed,
        "pending_hitl_created": pending_hitl_created,
        "human_resolution_done": human_resolution_done,
        "pending_open_count": pending_open_count,
        "ready_for_live": first_safe_executed and human_resolution_done,
    }
