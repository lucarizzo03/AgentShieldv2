import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import jwt
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


def _verify_jwt_bearer(token: str) -> AuthContext:
    settings = get_settings()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid JWT token",
        ) from exc

    agent_id = claims.get("agent_id") or claims.get("sub")
    if not isinstance(agent_id, str) or not agent_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWT missing agent identity",
        )

    return AuthContext(
        principal_id=str(claims.get("sub", agent_id)),
        method="jwt",
        agent_id=agent_id,
        claims=claims,
    )


async def verify_agent_auth(
    request: Request,
    authorization: str | None = Header(default=None),
    x_agent_id: str | None = Header(default=None),
    x_timestamp: str | None = Header(default=None),
    x_signature: str | None = Header(default=None),
    x_agent_key: str | None = Header(default=None),
) -> AuthContext:
    settings = get_settings()

    # Preferred production method #1: JWT bearer auth.
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        return _verify_jwt_bearer(token)

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
    if settings.app_env == "dev" and x_agent_key:
        return AuthContext(
            principal_id="dev-legacy-agent-key",
            method="legacy",
            agent_id=x_agent_id,
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing authentication. Provide Bearer JWT or HMAC signature headers.",
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

