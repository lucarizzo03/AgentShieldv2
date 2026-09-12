import asyncio
import logging
from datetime import datetime, timezone

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.postgres import async_engine
from app.db.redis import redis_client
from app.models.dashboard_notification import DashboardNotification
from app.models.pending_spend import PendingSpend
from app.models.spend_audit_log import SpendAuditLog

logger = logging.getLogger(__name__)

_SWEEP_INTERVAL = 60
_SWEEP_LOCK_KEY = "lock:hitl:expiry-sweeper"


async def _sweep_once() -> int:
    """Expire overdue PendingSpend rows. Returns number of rows expired."""
    now = datetime.now(timezone.utc)
    expired_count = 0

    async with AsyncSession(async_engine) as session:
        # Lock the candidate rows and skip any a resolve is already holding, so
        # the sweep cannot overwrite a resolution that commits mid-sweep.
        rows = (await session.exec(
            select(PendingSpend).where(
                PendingSpend.state == "WAITING_HUMAN",
                PendingSpend.expires_at <= now,
            ).with_for_update(skip_locked=True)
        )).all()

        for pending in rows:
            # Re-assert the state inside the locked transaction: the row may have
            # been resolved between the query planning and the lock being granted.
            await session.refresh(pending)
            if pending.state != "WAITING_HUMAN":
                continue

            pending.state = "EXPIRED"
            pending.resolved_at = now
            session.add(pending)

            original = pending.payload_json
            session.add(SpendAuditLog(
                request_id=pending.request_id,
                agent_id=pending.agent_id,
                declared_goal=original.get("declared_goal", ""),
                amount_cents=original.get("amount_cents", 0),
                currency=original.get("currency", "USD"),
                asset_type=original.get("asset_type", "STABLECOIN"),
                stablecoin_symbol=original.get("stablecoin_symbol"),
                network=original.get("network"),
                destination_address=original.get("destination_address"),
                vendor_url_or_name=original.get("vendor_url_or_name", ""),
                item_description=original.get("item_description", ""),
                quantitative_result=pending.verdict_snapshot.get("quantitative_result", {}),
                policy_result=pending.verdict_snapshot.get("policy_result", {}),
                semantic_result=pending.verdict_snapshot.get("semantic_result", {}),
                goal_drift_result=pending.verdict_snapshot.get("goal_drift_result", {}),
                verdict="SUSPICIOUS",
                status="EXPIRED",
            ))

            notification = (await session.exec(
                select(DashboardNotification).where(
                    DashboardNotification.request_id == pending.request_id,
                    DashboardNotification.status.in_(["OPEN", "ACKED"]),  # type: ignore[attr-defined]
                )
            )).first()
            if notification:
                notification.status = "RESOLVED"
                notification.acknowledged_by = "system:expiry-sweeper"
                notification.acknowledged_at = now
                notification.updated_at = now
                session.add(notification)

            expired_count += 1

        if expired_count:
            await session.commit()
            logger.info("HITL expiry sweep: expired %d request(s)", expired_count)

    return expired_count


async def run_expiry_sweeper() -> None:
    """Background task: sweep expired HITL requests every 60 seconds.

    The sweeper runs in every worker process, so each pass is guarded by a
    short-lived Redis lock: only one worker sweeps, and the others skip rather
    than racing to write duplicate EXPIRED audit rows.
    """
    logger.info("HITL expiry sweeper started (interval=%ds)", _SWEEP_INTERVAL)
    while True:
        await asyncio.sleep(_SWEEP_INTERVAL)
        try:
            acquired = await redis_client.set(_SWEEP_LOCK_KEY, "1", ex=_SWEEP_INTERVAL, nx=True)
            if not acquired:
                continue
            try:
                count = await _sweep_once()
            finally:
                await redis_client.delete(_SWEEP_LOCK_KEY)
            if count:
                logger.info("Expired %d stale HITL request(s)", count)
        except Exception:
            logger.exception("HITL expiry sweep failed")
