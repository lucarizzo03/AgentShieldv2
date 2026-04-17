from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlmodel import Session, select

from app.api.v1.schemas.hitl import HitlResolveRequest
from app.api.v1.schemas.spend import SpendRequest
from app.core.metrics import increment
from app.core.security import verify_hitl_webhook_signature
from app.db.postgres import get_session
from app.db.redis import get_redis
from app.models.pending_spend import PendingSpend
from app.models.spend_audit_log import SpendAuditLog
from app.policy.checks.quantitative import commit_budget_spend
from app.services.hitl.state_manager import apply_resolution, ensure_pending_is_resolvable
from app.services.payment.stripe_adapter import StripeAdapter
from app.services.payment.tempo_adapter import TempoAdapter

router = APIRouter(tags=["hitl"])


def _select_adapter(asset_type: str):
    return TempoAdapter() if asset_type == "STABLECOIN" else StripeAdapter()


@router.post("/hitl/resolve/{request_id}")
async def resolve_hitl_request(
    request_id: str,
    payload: HitlResolveRequest,
    _: None = Depends(verify_hitl_webhook_signature),
    session: Session = Depends(get_session),
    redis: Redis = Depends(get_redis),
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

    session.add(pending)
    session.commit()

    return {
        "request_id": request_id,
        "status": "RESOLVED",
        "decision": payload.decision,
        "resolved_at": pending.resolved_at,
        "payment": payment_payload,
    }

