import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import Header, HTTPException, Request, status
from sqlmodel import Session, select

from app.core.config import get_settings
from app.db.postgres import engine
from app.models.agent import Agent


@dataclass(slots=True)
class AuthContext:
    principal_id: str
    method: str
    agent_id: str | None = None
    claims: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class UserAuthContext:
    sub: str
    email: str | None
    display_name: str | None
    method: str = "dev-user-token"
    agent_id: str | None = None
    claims: dict[str, Any] = field(default_factory=dict)


def _normalize_signature(signature: str) -> str:
    return signature.removeprefix("sha256=").strip().lower()


def _body_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _validate_timestamp(timestamp: str, tolerance_seconds: int) -> None:
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature timestamp format",
        ) from exc
    now = datetime.now(timezone.utc)
    skew = abs((now - parsed.astimezone(timezone.utc)).total_seconds())
    if skew > tolerance_seconds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Signature timestamp outside allowed tolerance",
        )


def _verify_hmac(secret: str, message: str, signature: str) -> bool:
    expected = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, _normalize_signature(signature))


async def verify_agent_auth(
    request: Request,
    authorization: str | None = Header(default=None),
    x_agent_id: str | None = Header(default=None),
    x_timestamp: str | None = Header(default=None),
    x_signature: str | None = Header(default=None),
    x_agent_key: str | None = Header(default=None),
) -> AuthContext:
    settings = get_settings()

    if authorization and authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer auth is disabled in this MVP. Use HMAC headers.",
        )

    # Preferred production method #2: HMAC signed request.
    if x_agent_id and x_timestamp and x_signature:
        _validate_timestamp(x_timestamp, settings.signature_tolerance_seconds)
        body_hash = _body_sha256(await request.body())
        canonical_message = "\n".join(
            [
                request.method.upper(),
                request.url.path,
                x_timestamp,
                body_hash,
                x_agent_id,
            ]
        )
        with Session(engine) as session:
            agent = session.exec(select(Agent).where(Agent.agent_id == x_agent_id)).first()
            if not agent:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Unknown agent_id for HMAC authentication",
                )
            if not agent.hmac_secret:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Agent has no HMAC secret — rotate credentials first",
                )
            expected_secret = agent.hmac_secret

        if not _verify_hmac(expected_secret, canonical_message, x_signature):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid HMAC signature",
            )
        return AuthContext(principal_id=x_agent_id, method="hmac", agent_id=x_agent_id)

    # Dev-only compatibility for earlier prototype clients.
    # This fallback still enforces agent scoping by requiring both agent_id and a
    # matching per-agent key from the database.
    if settings.app_env == "dev" and x_agent_key:
        if not x_agent_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="x-agent-id header is required with x-agent-key in dev mode",
            )
        with Session(engine) as session:
            agent = session.exec(select(Agent).where(Agent.agent_id == x_agent_id)).first()
            if not agent:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Unknown agent_id for dev authentication",
                )
            if not agent.hmac_secret:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Agent has no HMAC secret — rotate credentials first",
                )
            if not hmac.compare_digest(agent.hmac_secret, x_agent_key):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid dev agent key",
                )

        return AuthContext(
            principal_id=x_agent_id,
            method="legacy",
            agent_id=x_agent_id,
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing authentication. Provide HMAC signature headers.",
    )


async def verify_user_auth(
    request: Request,
    authorization: str | None = Header(default=None),
    x_agent_id: str | None = Header(default=None),
    x_agent_key: str | None = Header(default=None),
) -> UserAuthContext:
    settings = get_settings()
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if settings.app_env == "dev" and token == settings.dev_user_token:
            return UserAuthContext(
                sub=settings.dev_user_sub,
                email=settings.dev_user_email,
                display_name="Local Dev User",
                method="dev-user-token",
                claims={"sub": settings.dev_user_sub, "email": settings.dev_user_email},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unsupported user token for current environment",
        )

    if settings.app_env == "dev" and x_agent_id and x_agent_key:
        with Session(engine) as session:
            agent = session.exec(select(Agent).where(Agent.agent_id == x_agent_id)).first()
            if not agent or not agent.hmac_secret:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Unknown agent credentials for dashboard authentication",
                )
            if not hmac.compare_digest(agent.hmac_secret, x_agent_key):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid agent key for dashboard authentication",
                )
        return UserAuthContext(
            sub=f"agent:{x_agent_id}",
            email=None,
            display_name=None,
            method="legacy-agent",
            agent_id=x_agent_id,
            claims={"agent_id": x_agent_id},
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing user authentication. Provide Bearer token or dev agent headers.",
    )


async def verify_hitl_webhook_signature(
    request: Request,
    x_webhook_signature: str | None = Header(default=None),
    x_webhook_timestamp: str | None = Header(default=None),
) -> None:
    settings = get_settings()

    # Dev shortcut kept for existing integration tests/manual smoke tests.
    if settings.app_env == "dev" and x_webhook_signature == "sig_ok":
        return

    if not x_webhook_signature or not x_webhook_timestamp:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing webhook signature headers",
        )

    _validate_timestamp(x_webhook_timestamp, settings.signature_tolerance_seconds)
    body_hash = _body_sha256(await request.body())
    canonical_message = "\n".join(
        [
            request.method.upper(),
            request.url.path,
            x_webhook_timestamp,
            body_hash,
        ]
    )
    if not _verify_hmac(settings.webhook_hmac_secret, canonical_message, x_webhook_signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )

