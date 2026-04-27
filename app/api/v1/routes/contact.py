from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlmodel import Session, select

from app.api.v1.schemas.contact import (
    HitlPreferencesUpdateRequest,
    HitlPreferencesUpdateResponse,
    PhoneVerificationConfirmRequest,
    PhoneVerificationConfirmResponse,
    PhoneVerificationStartRequest,
    PhoneVerificationStartResponse,
)
from app.core.config import get_settings
from app.core.security import AuthContext, verify_agent_auth
from app.db.postgres import get_session
from app.db.redis import get_redis
from app.models.agent import Agent
from app.services.hitl.otp import send_otp, verify_otp

router = APIRouter(tags=["contact"])


def _ensure_auth_agent_scope(auth_context: AuthContext, agent_id: str) -> None:
    if auth_context.agent_id and auth_context.agent_id != agent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated agent_id does not match requested agent_id",
        )


@router.post("/agents/{agent_id}/contact/phone/start", response_model=PhoneVerificationStartResponse)
async def start_phone_verification(
    agent_id: str,
    payload: PhoneVerificationStartRequest,
    auth_context: AuthContext = Depends(verify_agent_auth),
    session: Session = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    _ensure_auth_agent_scope(auth_context, agent_id)
    agent = session.exec(select(Agent).where(Agent.agent_id == agent_id)).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    result = await send_otp(redis=redis, agent_id=agent_id, phone_number=payload.phone_number)
    return {
        "agent_id": agent_id,
        "status": "OTP_SENT",
        "expires_in_seconds": result["expires_in_seconds"],
    }


@router.post("/agents/{agent_id}/contact/phone/verify", response_model=PhoneVerificationConfirmResponse)
async def confirm_phone_verification(
    agent_id: str,
    payload: PhoneVerificationConfirmRequest,
    auth_context: AuthContext = Depends(verify_agent_auth),
    session: Session = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    _ensure_auth_agent_scope(auth_context, agent_id)
    agent = session.exec(select(Agent).where(Agent.agent_id == agent_id)).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    settings = get_settings()
    dev_bypass = settings.app_env == "dev" and payload.code == "000000"
    is_valid = dev_bypass or await verify_otp(
        redis=redis,
        agent_id=agent_id,
        phone_number=payload.phone_number,
        code=payload.code,
    )
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification code")

    now = datetime.now(timezone.utc)
    agent.hitl_phone_number = payload.phone_number
    agent.hitl_phone_verified_at = now
    agent.updated_at = now
    session.add(agent)
    session.commit()

    return {
        "agent_id": agent_id,
        "status": "PHONE_VERIFIED",
        "phone_number": payload.phone_number,
        "verified_at": now,
    }


@router.patch("/agents/{agent_id}/preferences/hitl", response_model=HitlPreferencesUpdateResponse)
async def update_hitl_preferences(
    agent_id: str,
    payload: HitlPreferencesUpdateRequest,
    auth_context: AuthContext = Depends(verify_agent_auth),
    session: Session = Depends(get_session),
):
    _ensure_auth_agent_scope(auth_context, agent_id)
    agent = session.exec(select(Agent).where(Agent.agent_id == agent_id)).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    agent.hitl_primary_channel = payload.hitl_primary_channel
    agent.hitl_sms_fallback_high_risk = payload.hitl_sms_fallback_high_risk
    agent.updated_at = datetime.now(timezone.utc)
    session.add(agent)
    session.commit()

    return {
        "agent_id": agent_id,
        "hitl_primary_channel": agent.hitl_primary_channel,
        "hitl_sms_fallback_high_risk": agent.hitl_sms_fallback_high_risk,
    }

