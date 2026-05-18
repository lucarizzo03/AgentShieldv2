import asyncio
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.routes.agents import router as agents_router
from app.api.v1.routes.dashboard import router as dashboard_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.hitl import router as hitl_router
from app.api.v1.routes.onboarding import router as onboarding_router
from app.api.v1.routes.spend import router as spend_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.postgres import async_engine, create_db_and_tables
from app.models.agent import Agent
from app.models.spend_audit_log import SpendAuditLog
from app.services.hitl.expiry_sweeper import run_expiry_sweeper


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_db_and_tables()
    sweeper = asyncio.create_task(run_expiry_sweeper())
    yield
    sweeper.cancel()
    try:
        await sweeper
    except asyncio.CancelledError:
        pass


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(title="AgentShield", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "x-agent-id",
            "x-timestamp",
            "x-signature",
            "x-webhook-signature",
            "x-webhook-timestamp",
            "x-request-id",
        ],
        expose_headers=["x-request-id", "x-latency-ms"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        request_id = request.headers.get("x-request-id", f"trace_{uuid4().hex[:12]}")
        encoded_errors = jsonable_encoder(exc.errors())
        logged_request_id = None

        if request.method.upper() == "POST" and request.url.path == "/v1/spend-request":
            try:
                payload = await request.json()
            except Exception:
                payload = None

            if isinstance(payload, dict):
                agent_id = payload.get("agent_id")
                if isinstance(agent_id, str) and agent_id:
                    raw_amount = payload.get("amount_cents")
                    try:
                        parsed_amount = int(raw_amount)
                    except Exception:
                        parsed_amount = 1
                    amount_cents = parsed_amount if parsed_amount > 0 else 1
                    asset_type = payload.get("asset_type")
                    if asset_type not in {"STABLECOIN", "FIAT"}:
                        asset_type = "STABLECOIN"
                    async with AsyncSession(async_engine) as session:
                        agent = (await session.exec(select(Agent).where(Agent.agent_id == agent_id))).first()
                        if agent:
                            logged_request_id = f"req_val_{uuid4().hex[:18]}"
                            session.add(
                                SpendAuditLog(
                                    request_id=logged_request_id,
                                    agent_id=agent_id,
                                    declared_goal=str(payload.get("declared_goal") or "VALIDATION_REJECTED"),
                                    amount_cents=amount_cents,
                                    currency=str(payload.get("currency") or "USD"),
                                    asset_type=asset_type,
                                    stablecoin_symbol=payload.get("stablecoin_symbol"),
                                    network=payload.get("network"),
                                    destination_address=payload.get("destination_address"),
                                    vendor_url_or_name=str(payload.get("vendor_url_or_name") or "unknown"),
                                    item_description=str(payload.get("item_description") or "Validation rejected"),
                                    quantitative_result={"validation_rejected": True},
                                    policy_result={"validation_errors": encoded_errors},
                                    semantic_result={},
                                    goal_drift_result={},
                                    verdict="MALICIOUS",
                                    status="BLOCKED",
                                )
                            )
                            await session.commit()

        return JSONResponse(
            status_code=422,
            content={
                "message": "Request validation failed",
                "detail": encoded_errors,
                "request_id": logged_request_id,
                "trace_id": request_id,
            },
        )

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id", f"trace_{uuid4().hex[:12]}")
        request.state.request_id = request_id
        start = perf_counter()
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        response.headers["x-latency-ms"] = f"{(perf_counter() - start) * 1000:.2f}"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        )
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        return response

    app.include_router(health_router)
    app.include_router(spend_router, prefix="/v1")
    app.include_router(hitl_router, prefix="/v1")
    app.include_router(agents_router, prefix="/v1")
    app.include_router(dashboard_router, prefix="/v1")
    app.include_router(onboarding_router, prefix="/v1")
    return app


app = create_app()

