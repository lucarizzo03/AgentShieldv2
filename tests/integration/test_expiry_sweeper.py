"""The expiry sweeper must never clobber a resolution or double-expire a row."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, select

from app.db.postgres import engine
from app.models import PendingSpend
from app.models.spend_audit_log import SpendAuditLog
from app.services.hitl.expiry_sweeper import _sweep_once
from tests.integration.test_spend_hitl_flow import _reset_db, _seed_agent


def _seed_pending(state: str = "WAITING_HUMAN") -> str:
    request_id = str(uuid.uuid4())
    with Session(engine) as session:
        session.add(PendingSpend(
            request_id=request_id,
            agent_id="agent_demo",
            state=state,
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            payload_json={
                "agent_id": "agent_demo",
                "declared_goal": "Buy API credits",
                "amount_cents": 1200,
                "currency": "USD",
                "asset_type": "STABLECOIN",
                "vendor_url_or_name": "tempo",
                "item_description": "Agent credit top-up",
            },
            verdict_snapshot={},
        ))
        session.commit()
    return request_id


def _audit_rows(request_id: str) -> list[SpendAuditLog]:
    with Session(engine) as session:
        return list(session.exec(
            select(SpendAuditLog).where(SpendAuditLog.request_id == request_id)
        ).all())


@pytest.mark.asyncio
async def test_sweep_expires_overdue_request_once() -> None:
    _reset_db()
    _seed_agent()
    request_id = _seed_pending()

    assert await _sweep_once() == 1
    assert await _sweep_once() == 0

    with Session(engine) as session:
        pending = session.exec(
            select(PendingSpend).where(PendingSpend.request_id == request_id)
        ).first()
        assert pending is not None
        assert pending.state == "EXPIRED"
    assert len(_audit_rows(request_id)) == 1


@pytest.mark.asyncio
async def test_sweep_leaves_already_resolved_request_untouched() -> None:
    _reset_db()
    _seed_agent()
    request_id = _seed_pending(state="APPROVED")

    assert await _sweep_once() == 0

    with Session(engine) as session:
        pending = session.exec(
            select(PendingSpend).where(PendingSpend.request_id == request_id)
        ).first()
        assert pending is not None
        assert pending.state == "APPROVED"
    assert _audit_rows(request_id) == []
