from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from redis.asyncio import Redis
from sqlmodel import Session, select

from app.api.v1.schemas.hitl import HitlResolveRequest
from app.api.v1.schemas.spend import SpendRequest
from app.core.metrics import increment
from app.core.security import verify_hitl_webhook_signature
from app.db.postgres import get_session
from app.db.redis import get_redis
from app.models.dashboard_notification import DashboardNotification
from app.models.pending_spend import PendingSpend
from app.models.spend_audit_log import SpendAuditLog
from app.policy.checks.quantitative import commit_budget_spend
from app.services.hitl.sms_parser import parse_sms_decision
from app.services.hitl.state_manager import apply_resolution, ensure_pending_is_resolvable
from app.services.payment.stripe_adapter import StripeAdapter
from app.services.payment.tempo_adapter import TempoAdapter

router = APIRouter(tags=["hitl"])


def _select_adapter(asset_type: str):
    return TempoAdapter() if asset_type == "STABLECOIN" else StripeAdapter()


async def _resolve_pending(
    *,
    request_id: str,
    payload: HitlResolveRequest,
    session: Session,
    redis: Redis,
):
    pending = session.exec(select(PendingSpend).where(PendingSpend.request_id == request_id)).first()
    if not pending:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pending request not found")

    try:
        ensure_pending_is_resolvable(pending)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    apply_resolution(pending, payload.decision, payload.resolver_id)
    payment_payload = {"executed": False, "provider": None, "provider_txn_id": None}

    if payload.decision == "APPROVE":
        increment("hitl.decision.approve")
        original = SpendRequest.model_validate(pending.payload_json)
        payment = await _select_adapter(original.asset_type).execute(request_id=request_id, spend_request=original)
        await commit_budget_spend(
            redis=redis,
            agent_id=original.agent_id,
            asset_type=original.asset_type,
            amount_cents=original.amount_cents,
        )
        payment_payload = {
            "executed": True,
            "provider": payment["provider"],
            "provider_txn_id": payment["provider_txn_id"],
        }

        audit = SpendAuditLog(
            request_id=request_id,
            agent_id=original.agent_id,
            declared_goal=original.declared_goal,
            amount_cents=original.amount_cents,
            currency=original.currency,
            asset_type=original.asset_type,
            stablecoin_symbol=original.stablecoin_symbol,
            network=original.network,
            destination_address=original.destination_address,
            vendor_url_or_name=original.vendor_url_or_name,
            item_description=original.item_description,
            quantitative_result=pending.verdict_snapshot.get("quantitative_result", {}),
            policy_result=pending.verdict_snapshot.get("policy_result", {}),
            semantic_result=pending.verdict_snapshot.get("semantic_result", {}),
            verdict="SAFE",
            status="APPROVED_BY_HUMAN_EXECUTED",
            payment_provider=payment["provider"],
            payment_txn_id=payment["provider_txn_id"],
            onchain_tx_hash=payment.get("onchain_tx_hash"),
        )
        session.add(audit)
    else:
        increment("hitl.decision.deny")
        original = pending.payload_json
        audit = SpendAuditLog(
            request_id=f"{request_id}_deny_{int(datetime.now(timezone.utc).timestamp())}",
            agent_id=original["agent_id"],
            declared_goal=original["declared_goal"],
            amount_cents=original["amount_cents"],
            currency=original["currency"],
            asset_type=original["asset_type"],
            stablecoin_symbol=original.get("stablecoin_symbol"),
            network=original.get("network"),
            destination_address=original.get("destination_address"),
            vendor_url_or_name=original["vendor_url_or_name"],
            item_description=original["item_description"],
            quantitative_result=pending.verdict_snapshot.get("quantitative_result", {}),
            policy_result=pending.verdict_snapshot.get("policy_result", {}),
            semantic_result=pending.verdict_snapshot.get("semantic_result", {}),
            verdict="MALICIOUS",
            status="DENIED_BY_HUMAN",
        )
        session.add(audit)

    notification = session.exec(
        select(DashboardNotification).where(DashboardNotification.request_id == request_id)
    ).first()
    if notification and notification.status in {"OPEN", "ACKED"}:
        notification.status = "RESOLVED"
        notification.acknowledged_by = payload.resolver_id
        notification.acknowledged_at = datetime.now(timezone.utc)
        notification.updated_at = datetime.now(timezone.utc)
        session.add(notification)

    session.add(pending)
    session.commit()
    return {
        "request_id": request_id,
        "status": "RESOLVED",
        "decision": payload.decision,
        "resolved_at": pending.resolved_at,
        "payment": payment_payload,
    }


@router.post("/hitl/resolve/{request_id}")
async def resolve_hitl_request(
    request_id: str,
    payload: HitlResolveRequest,
    _: None = Depends(verify_hitl_webhook_signature),
    session: Session = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    return await _resolve_pending(request_id=request_id, payload=payload, session=session, redis=redis)


@router.post("/hitl/sms/inbound")
async def inbound_hitl_sms(
    request: Request,
    _: None = Depends(verify_hitl_webhook_signature),
    session: Session = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    form = await request.form()
    body = str(form.get("Body", "")).strip()
    from_phone = str(form.get("From", "")).strip()
    message_sid = str(form.get("MessageSid", "")).strip() or None

    parsed = parse_sms_decision(body)
    if not parsed:
        return Response(
            content=(
                "<Response><Message>"
                "Invalid command. Reply with APPROVE &lt;request_id&gt; or DENY &lt;request_id&gt;."
                "</Message></Response>"
            ),
            media_type="application/xml",
        )

    decision, request_id = parsed
    pending = session.exec(select(PendingSpend).where(PendingSpend.request_id == request_id)).first()
    if not pending:
        return Response(
            content="<Response><Message>Request ID not found.</Message></Response>",
            media_type="application/xml",
        )

    if (pending.hitl_contact or "").strip() != from_phone:
        return Response(
            content="<Response><Message>Phone number not authorized for this request.</Message></Response>",
            media_type="application/xml",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    payload = HitlResolveRequest(
        decision=decision,
        resolver_id=f"sms:{from_phone}",
        channel="sms",
        provider_message_id=message_sid,
    )
    try:
        await _resolve_pending(request_id=request_id, payload=payload, session=session, redis=redis)
    except HTTPException as exc:
        return Response(
            content=f"<Response><Message>Unable to resolve request: {exc.detail}</Message></Response>",
            media_type="application/xml",
            status_code=exc.status_code,
        )

    return Response(
        content=f"<Response><Message>{decision} recorded for {request_id}.</Message></Response>",
        media_type="application/xml",
    )

