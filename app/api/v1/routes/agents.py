from datetime import datetime, timezone
from secrets import token_urlsafe
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from app.api.v1.schemas.agent import (
    AgentCreateRequest,
    AgentCreateResponse,
    AgentListResponse,
    AgentRotateHmacResponse,
    AgentSettingsUpdateRequest,
    AgentScopesUpdateRequest,
)
from app.core.security import AuthContext, UserAuthContext, verify_agent_auth, verify_user_auth
from app.db.postgres import get_session
from app.models.agent import Agent
from app.services.activity_log import append_agent_activity
from app.services.user_identity import get_or_create_user

router = APIRouter(tags=["agents"])


def _cents_to_usd_setting(cents: int) -> int:
    # 100_000_000 cents is our sentinel for "effectively unlimited".
    return 0 if cents >= 100_000_000 else int(cents // 100)


@router.post("/agents", response_model=AgentCreateResponse)
async def create_agent(
    payload: AgentCreateRequest,
    auth: UserAuthContext = Depends(verify_user_auth),
    session: Session = Depends(get_session),
):
    if auth.agent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agent credentials cannot create agents. Sign in as a user.",
        )
    user = get_or_create_user(session, auth)
    existing = session.exec(
        select(Agent)
        .where(Agent.display_name == payload.agent_name)
        .where(Agent.owner_user_id == user.id)
    ).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent name already exists")

    now = datetime.now(timezone.utc)
    agent_id = f"agt_{uuid4().hex[:18]}"
    hmac_secret = f"sk_live_{token_urlsafe(18)}"
    agent = Agent(
        agent_id=agent_id,
        display_name=payload.agent_name,
        daily_budget_limit_cents=payload.daily_spend_limit_usd * 100 if payload.daily_spend_limit_usd > 0 else 100_000_000,
        per_txn_auto_approve_limit_cents=payload.per_transaction_limit_usd * 100 if payload.per_transaction_limit_usd > 0 else 100_000_000,
        hitl_required_over_cents=payload.auto_approve_under_usd * 100,
        blocked_vendors=payload.blocked_vendors,
        allowed_networks=payload.allowed_networks or ["base"],
        allowed_stablecoins=payload.allowed_tokens or ["USDC"],
        allowed_scopes=payload.allowed_scopes,
        currency="USD",
        owner_user_id=user.id,
        hmac_secret=hmac_secret,
        hmac_secret_rotated_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(agent)
    append_agent_activity(
        session,
        agent_id=agent_id,
        user_id=user.id,
        event_type="AGENT_CREATED",
        event_payload={"display_name": payload.agent_name},
    )
    session.commit()

    return {
        "agent_id": agent_id,
        "hmac_secret": hmac_secret,
        "display_name": payload.agent_name,
        "created_at": now,
    }


@router.get("/agents", response_model=AgentListResponse)
async def list_agents(
    auth: UserAuthContext = Depends(verify_user_auth),
    session: Session = Depends(get_session),
):
    if auth.agent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agent credentials cannot list user agents. Sign in as a user.",
        )
    user = get_or_create_user(session, auth)
    agents = session.exec(
        select(Agent)
        .where(Agent.owner_user_id == user.id)
        .order_by(Agent.created_at.desc())
    ).all()
    return {
        "agents": [
            {
                "agent_id": a.agent_id,
                "display_name": a.display_name,
                "status": a.status,
                "daily_spend_limit_usd": _cents_to_usd_setting(a.daily_budget_limit_cents),
                "per_transaction_limit_usd": _cents_to_usd_setting(a.per_txn_auto_approve_limit_cents),
                "auto_approve_under_usd": int((a.hitl_required_over_cents or 0) // 100),
                "blocked_vendors": a.blocked_vendors or [],
                "allowed_networks": a.allowed_networks or [],
                "allowed_tokens": a.allowed_stablecoins or [],
                "allowed_scopes": a.allowed_scopes or [],
            }
            for a in agents
        ]
    }


@router.patch("/agents/{agent_id}")
async def update_agent_settings(
    agent_id: str,
    payload: AgentSettingsUpdateRequest,
    auth: UserAuthContext = Depends(verify_user_auth),
    session: Session = Depends(get_session),
):
    user = get_or_create_user(session, auth)
    agent = session.exec(
        select(Agent).where(Agent.agent_id == agent_id).where(Agent.owner_user_id == user.id)
    ).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    now = datetime.now(timezone.utc)
    agent.display_name = payload.agent_name
    agent.daily_budget_limit_cents = payload.daily_spend_limit_usd * 100 if payload.daily_spend_limit_usd > 0 else 100_000_000
    agent.per_txn_auto_approve_limit_cents = (
        payload.per_transaction_limit_usd * 100 if payload.per_transaction_limit_usd > 0 else 100_000_000
    )
    agent.hitl_required_over_cents = payload.auto_approve_under_usd * 100
    agent.blocked_vendors = payload.blocked_vendors
    agent.allowed_networks = payload.allowed_networks or ["base"]
    agent.allowed_stablecoins = payload.allowed_tokens or ["USDC"]
    agent.allowed_scopes = payload.allowed_scopes
    agent.updated_at = now

    session.add(agent)
    append_agent_activity(
        session,
        agent_id=agent.agent_id,
        user_id=user.id,
        event_type="AGENT_SETTINGS_UPDATED",
        event_payload={
            "display_name": agent.display_name,
            "daily_spend_limit_usd": payload.daily_spend_limit_usd,
            "per_transaction_limit_usd": payload.per_transaction_limit_usd,
            "auto_approve_under_usd": payload.auto_approve_under_usd,
        },
    )
    session.commit()
    return {"agent_id": agent.agent_id, "updated_at": now}


@router.patch("/agents/{agent_id}/scopes")
async def update_agent_scopes(
    agent_id: str,
    payload: AgentScopesUpdateRequest,
    auth: UserAuthContext = Depends(verify_user_auth),
    session: Session = Depends(get_session),
):
    user = get_or_create_user(session, auth)
    agent = session.exec(
        select(Agent).where(Agent.agent_id == agent_id).where(Agent.owner_user_id == user.id)
    ).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    agent.allowed_scopes = payload.allowed_scopes
    agent.updated_at = datetime.now(timezone.utc)
    session.add(agent)
    session.commit()
    return {"agent_id": agent_id, "allowed_scopes": agent.allowed_scopes}


@router.post("/agents/{agent_id}/credentials/hmac/rotate", response_model=AgentRotateHmacResponse)
async def rotate_agent_hmac(
    agent_id: str,
    auth: AuthContext = Depends(verify_agent_auth),
    session: Session = Depends(get_session),
):
    if auth.agent_id != agent_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot rotate another agent's credentials")
    # Rotation stays agent-authenticated, not user-authenticated.
    agent = session.exec(select(Agent).where(Agent.agent_id == agent_id)).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    now = datetime.now(timezone.utc)
    agent.hmac_secret = f"sk_live_{token_urlsafe(18)}"
    agent.hmac_secret_rotated_at = now
    agent.updated_at = now
    session.add(agent)
    session.commit()
    return {
        "agent_id": agent.agent_id,
        "hmac_secret": agent.hmac_secret,
        "rotated_at": now,
    }

