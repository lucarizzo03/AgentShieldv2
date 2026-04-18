from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request

from app.api.v1.routes.contact import router as contact_router
from app.api.v1.routes.dashboard import router as dashboard_router
from app.api.v1.routes.hitl import router as hitl_router
from app.api.v1.routes.spend import router as spend_router
from app.core.logging import configure_logging
from app.db.postgres import create_db_and_tables


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="AgentShield", version="0.1.0")

    @app.on_event("startup")
    def on_startup() -> None:
        create_db_and_tables()

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id", f"trace_{uuid4().hex[:12]}")
        request.state.request_id = request_id
        start = perf_counter()
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        response.headers["x-latency-ms"] = f"{(perf_counter() - start) * 1000:.2f}"
        return response

    app.include_router(spend_router, prefix="/v1")
    app.include_router(hitl_router, prefix="/v1")
    app.include_router(contact_router, prefix="/v1")
    app.include_router(dashboard_router, prefix="/v1")
    return app


app = create_app()

