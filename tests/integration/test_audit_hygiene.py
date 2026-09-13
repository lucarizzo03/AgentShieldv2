"""Audit-log hygiene: provenance stamps (#23) and unpolluted decision rows (#27)."""

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db.postgres import engine
from app.db.redis import get_redis
from app.main import app
from app.models.spend_audit_log import SpendAuditLog
from app.policy.provenance import ENGINE_VERSION
from tests.integration.test_full_scenarios import (
    _FIAT,
    FakeRedis,
    _mock_semantic,
    _reset_db,
    _seed_agent,
    _sign_agent,
)


def setup_function() -> None:
    _reset_db()
    _seed_agent()
    app.dependency_overrides[get_redis] = lambda: FakeRedis()
    _mock_semantic("ALIGNED")


def teardown_function() -> None:
    app.dependency_overrides.clear()


def _rows() -> list[SpendAuditLog]:
    with Session(engine) as session:
        return list(session.exec(select(SpendAuditLog)).all())


def test_decision_rows_carry_engine_provenance() -> None:
    content, headers = _sign_agent(_FIAT)
    with TestClient(app) as client:
        resp = client.post("/v1/spend-request", content=content, headers=headers)
    assert resp.status_code == 200, resp.text

    (row,) = _rows()
    provenance = row.engine_provenance
    assert provenance["engine_version"] == ENGINE_VERSION
    assert provenance["model_name"]
    assert provenance["prompt_versions"]["semantic_alignment"]
    assert provenance["thresholds"]["semantic_aligned_min_score"]


def test_validation_failure_is_not_recorded_as_a_block() -> None:
    malformed = {**_FIAT, "amount_cents": -5, "idempotency_key": "test-validation-001"}
    content, headers = _sign_agent(malformed)
    with TestClient(app) as client:
        resp = client.post("/v1/spend-request", content=content, headers=headers)
    assert resp.status_code == 422, resp.text

    (row,) = _rows()
    assert row.verdict == "REJECTED"
    assert row.status == "VALIDATION_REJECTED"
    assert row.verdict != "MALICIOUS"
