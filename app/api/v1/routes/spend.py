from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from redis.asyncio import Redis
from sqlmodel import Session, select

from app.api.v1.schemas.spend import SpendRequest
from app.core.config import get_settings
from app.core.metrics import increment
from app.core.security import AuthContext, verify_agent_auth
from app.db.postgres import get_session
from app.db.redis import get_redis
from app.models.agent import Agent
from app.models.dashboard_notification import DashboardNotification
from app.models.pending_spend import PendingSpend
from app.models.spend_audit_log import SpendAuditLog
from app.policy.checks.quantitative import commit_budget_spend, transaction_fingerprint
from app.policy.engine import run_financial_triangulation
from app.services.hitl.notifier import HitlNotifier
from app.services.idempotency import cache_idempotent_response, read_cached_idempotent_response
from app.services.payment.stripe_adapter import StripeAdapter
from app.services.payment.tempo_adapter import TempoAdapter
from app.services.slm.client import LocalSlmClient

router = APIRouter(tags=["spend"])


def _select_adapter(asset_type: str):
    return TempoAdapter() if asset_type == "STABLECOIN" else StripeAdapter()


def _is_high_risk_suspicious(reasons: list[str]) -> bool:
    high_risk_flags = {
        "SEMANTIC_MISMATCH_MEDIUM",
        "LOOP_PATTERN_DETECTED",
        "DESTINATION_BURST_DETECTED",
        "BUDGET_DAILY_LIMIT_EXCEEDED",
    }
    return any(reason in high_risk_flags for reason in reasons)


@router.post("/spend-request")
async def spend_request(
    payload: SpendRequest,
    response: Response,
    auth_context: AuthContext = Depends(verify_agent_auth),
    session: Session = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    if auth_context.agent_id and auth_context.agent_id != payload.agent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated agent_id does not match request payload agent_id",
        )

    agent = session.exec(select(Agent).where(Agent.agent_id == payload.agent_id)).first()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    if agent.status != "ACTIVE":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agent is not active")

    cached = await read_cached_idempotent_response(redis, payload.agent_id, payload.idempotency_key)
    if cached:
        response.status_code = int(cached.get("_http_status", 200))
        return cached["body"]

    request_id = f"req_{uuid4().hex[:18]}"
    fingerprint = transaction_fingerprint(
        vendor=payload.vendor_url_or_name,
        amount_cents=payload.amount_cents,
        item_description=payload.item_description,
        asset_type=payload.asset_type,
        stablecoin_symbol=payload.stablecoin_symbol,
        network=payload.network,
        destination_address=payload.destination_address,
    )

    tri = await run_financial_triangulation(
        redis=redis,
        slm_client=LocalSlmClient(),
        agent=agent,
        amount_cents=payload.amount_cents,
        vendor_url_or_name=payload.vendor_url_or_name,
        item_description=payload.item_description,
        declared_goal=payload.declared_goal,
        asset_type=payload.asset_type,
        stablecoin_symbol=payload.stablecoin_symbol,
        network=payload.network,
        destination_address=payload.destination_address,
        fingerprint=fingerprint,
    )

    now = datetime.now(timezone.utc)
    if tri.verdict == "SAFE":
        increment("spend.verdict.safe")
        payment = await _select_adapter(payload.asset_type).execute(request_id=request_id, spend_request=payload)
        audit = SpendAuditLog(
            request_id=request_id,
            agent_id=payload.agent_id,
            declared_goal=payload.declared_goal,
            amount_cents=payload.amount_cents,
            currency=payload.currency,
            asset_type=payload.asset_type,
            stablecoin_symbol=payload.stablecoin_symbol,
            network=payload.network,
            destination_address=payload.destination_address,
            vendor_url_or_name=payload.vendor_url_or_name,
            item_description=payload.item_description,
            quantitative_result=tri.quantitative_result,
            policy_result=tri.policy_result,
            semantic_result=tri.semantic_result,
            verdict="SAFE",
            status="APPROVED_EXECUTED",
            payment_provider=payment["provider"],
            payment_txn_id=payment["provider_txn_id"],
            onchain_tx_hash=payment.get("onchain_tx_hash"),
        )
        session.add(audit)
        session.commit()
        await commit_budget_spend(redis, payload.agent_id, payload.asset_type, payload.amount_cents)
        body = {
            "request_id": request_id,
            "status": "APPROVED_EXECUTED",
            "verdict": "SAFE",
            "approved_amount_cents": payload.amount_cents,
            "currency": payload.currency,
            "payment": payment,
            "reasons": tri.reasons,
        }
        await cache_idempotent_response(redis, payload.agent_id, payload.idempotency_key, {"_http_status": 200, "body": body})
        return body

    if tri.verdict == "MALICIOUS":
        increment("spend.verdict.malicious")
        audit = SpendAuditLog(
            request_id=request_id,
            agent_id=payload.agent_id,
            declared_goal=payload.declared_goal,
            amount_cents=payload.amount_cents,
            currency=payload.currency,
            asset_type=payload.asset_type,
            stablecoin_symbol=payload.stablecoin_symbol,
            network=payload.network,
            destination_address=payload.destination_address,
            vendor_url_or_name=payload.vendor_url_or_name,
            item_description=payload.item_description,
            quantitative_result=tri.quantitative_result,
            policy_result=tri.policy_result,
            semantic_result=tri.semantic_result,
            verdict="MALICIOUS",
            status="BLOCKED",
        )
        session.add(audit)
        session.commit()
        body = {
            "request_id": request_id,
            "status": "BLOCKED",
            "verdict": "MALICIOUS",
            "block_code": "POLICY_HARD_DENY",
            "reasons": tri.reasons,
            "next_action": "DO_NOT_RETRY",
        }
        response.status_code = status.HTTP_403_FORBIDDEN
        await cache_idempotent_response(redis, payload.agent_id, payload.idempotency_key, {"_http_status": 403, "body": body})
        return body

    settings = get_settings()
    increment("spend.verdict.suspicious")
    sms_fallback_triggered = (
        agent.hitl_primary_channel == "dashboard"
        and agent.hitl_sms_fallback_high_risk
        and bool(agent.hitl_phone_number)
        and bool(agent.hitl_phone_verified_at)
        and _is_high_risk_suspicious(tri.reasons)
    )

    pending = PendingSpend(
        request_id=request_id,
        agent_id=payload.agent_id,
        payload_json=payload.model_dump(mode="json"),
        verdict_snapshot={
            "verdict": tri.verdict,
            "reasons": tri.reasons,
            "quantitative_result": tri.quantitative_result,
            "policy_result": tri.policy_result,
            "semantic_result": tri.semantic_result,
        },
        state="WAITING_HUMAN",
        hitl_channel="sms" if sms_fallback_triggered else "dashboard",
        hitl_contact=agent.hitl_phone_number if sms_fallback_triggered else None,
        expires_at=now + timedelta(seconds=settings.hitl_default_timeout_seconds),
    )
    notification = DashboardNotification(
        request_id=request_id,
        agent_id=payload.agent_id,
        category="HITL_PENDING",
        priority="HIGH" if _is_high_risk_suspicious(tri.reasons) else "NORMAL",
        status="OPEN",
        summary=(
            f"HITL review required for {payload.amount_cents} {payload.currency} "
            f"to {payload.vendor_url_or_name}"
        ),
        payload_json={
            "request_id": request_id,
            "verdict": "SUSPICIOUS",
            "reasons": tri.reasons,
            "declared_goal": payload.declared_goal,
            "amount_cents": payload.amount_cents,
            "currency": payload.currency,
            "vendor_url_or_name": payload.vendor_url_or_name,
            "item_description": payload.item_description,
            "asset_type": payload.asset_type,
            "stablecoin_symbol": payload.stablecoin_symbol,
            "network": payload.network,
            "destination_address": payload.destination_address,
            "quantitative_result": tri.quantitative_result,
            "policy_result": tri.policy_result,
            "semantic_result": tri.semantic_result,
            "expires_at": (now + timedelta(seconds=settings.hitl_default_timeout_seconds)).isoformat(),
        },
    )
    audit = SpendAuditLog(
        request_id=request_id,
        agent_id=payload.agent_id,
        declared_goal=payload.declared_goal,
        amount_cents=payload.amount_cents,
        currency=payload.currency,
        asset_type=payload.asset_type,
        stablecoin_symbol=payload.stablecoin_symbol,
        network=payload.network,
        destination_address=payload.destination_address,
        vendor_url_or_name=payload.vendor_url_or_name,
        item_description=payload.item_description,
        quantitative_result=tri.quantitative_result,
        policy_result=tri.policy_result,
        semantic_result=tri.semantic_result,
        verdict="SUSPICIOUS",
        status="PENDING_HITL",
    )
    session.add(pending)
    session.add(notification)
    session.add(audit)
    session.commit()
    if sms_fallback_triggered:
        await HitlNotifier().send_sms(agent=agent, pending=pending)

    body = {
        "request_id": request_id,
        "status": "PENDING_HITL",
        "verdict": "SUSPICIOUS",
        "hitl": {
            "state": "WAITING_HUMAN_TEXT_RESPONSE" if sms_fallback_triggered else "WAITING_HUMAN_REVIEW",
            "channel": "sms" if sms_fallback_triggered else "dashboard",
            "requested_at": now,
            "expires_at": pending.expires_at,
        },
        "reasons": tri.reasons,
        "next_action": "AGENT_MUST_WAIT",
    }
    response.status_code = status.HTTP_202_ACCEPTED
    await cache_idempotent_response(redis, payload.agent_id, payload.idempotency_key, {"_http_status": 202, "body": body})
    return body

