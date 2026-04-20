from datetime import datetime, timezone
from secrets import token_urlsafe
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status
from sqlmodel import Session, select

from app.api.v1.schemas.agent import (
    AgentCreateRequest,
    AgentCreateResponse,
    AgentListResponse,
    AgentRotateHmacResponse,
)
from app.db.postgres import engine
from app.models.agent import Agent

router = APIRouter(tags=["agents"])


@router.post("/agents", response_model=AgentCreateResponse)
async def create_agent(payload: AgentCreateRequest):
    with Session(engine) as session:
        existing = session.exec(select(Agent).where(Agent.display_name == payload.agent_name)).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Agent name already exists")

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

        return {
            "agent_id": agent_id,
            "hmac_secret": hmac_secret,
            "display_name": payload.agent_name,
            "created_at": now,
        }


@router.get("/agents", response_model=AgentListResponse)
async def list_agents():
    with Session(engine) as session:
        agents = session.exec(select(Agent).order_by(Agent.created_at.desc())).all()
        return {
            "agents": [
                {
                    "agent_id": a.agent_id,
                    "display_name": a.display_name,
                    "status": a.status,
                    "hitl_primary_channel": a.hitl_primary_channel,
                }
                for a in agents
            ]
        }


@router.post("/agents/{agent_id}/credentials/hmac/rotate", response_model=AgentRotateHmacResponse)
async def rotate_agent_hmac(agent_id: str):
    with Session(engine) as session:
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

