# AgentShield Python SDK — v2 Requirements

This document captures exactly what the Python SDK needs to expose for a buying agent to integrate with AgentShield v2. It was written from the perspective of a real integration that hit the gap between the published SDK (v0.1.2) and the documented v2 API.

---

## The Problem

The published PyPI package (`agentshield==0.1.2`) exports:

```python
['AgentShieldClient', 'SecureAgent', 'AgentShieldException', 'ConfigurationError',
 'NetworkError', 'PolicyEvaluationError', 'SecurityException', 'interceptor']
```

The documented v2 API requires:

```python
from agentshield import AsyncAgentShield, SpendRequest
```

Neither `AsyncAgentShield` nor `SpendRequest` exist in v0.1.2. The v0.1.2 client also uses `requests` (blocking) and exposes a tool-monitoring API (`log_agent_call`), not the spend-request payment firewall.

Any agent that follows the docs and runs `pip install agentshield` will get an `ImportError` immediately.

---

## What the SDK Needs to Export

### `SpendRequest`

```python
from dataclasses import dataclass
from typing import Literal, Optional

@dataclass
class SpendRequest:
    agent_id: str
    declared_goal: str
    amount_cents: int           # integer cents — never float
    currency: str               # ISO 3-letter: USD, ETH, etc.
    vendor_url_or_name: str
    item_description: str
    asset_type: Literal["FIAT", "STABLECOIN"]
    stablecoin_symbol: Optional[str] = None   # USDC, USDT — required if STABLECOIN
    network: Optional[str] = None             # base, ethereum, solana — required if STABLECOIN
    destination_address: Optional[str] = None # on-chain address — required if STABLECOIN
    idempotency_key: Optional[str] = None
    agent_callback_url: Optional[str] = None
```

### `SpendResponse`

```python
@dataclass
class SpendResponse:
    verdict: Literal["SAFE", "SUSPICIOUS", "MALICIOUS"]
    status_code: int        # 200 | 202 | 403
    request_id: str
    raw_status: Optional[str] = None  # e.g. PENDING_HITL, APPROVED_EXECUTED
```

### `AsyncAgentShield`

```python
class AsyncAgentShield:
    def __init__(
        self,
        agent_id: str,
        hmac_secret: str,
        base_url: str = "https://agentshieldv2-backend-production.up.railway.app/v1",
    ): ...

    async def spend_request(self, req: SpendRequest) -> SpendResponse:
        """
        200 → SpendResponse(verdict="SAFE")
        202 → SpendResponse(verdict="SUSPICIOUS")  — agent must poll get_spend_status()
        403 → raises AgentShieldBlockedError        — hard deny, do not retry
        401 → raises AgentShieldAuthError           — rotate credentials
        """
        ...

    async def get_spend_status(self, request_id: str) -> SpendResponse:
        """Poll resolution of a SUSPICIOUS (202) request."""
        ...

    async def aclose(self) -> None: ...
    async def __aenter__(self) -> "AsyncAgentShield": ...
    async def __aexit__(self, *_) -> None: ...
```

### `AgentShield` (sync)

```python
class AgentShield:
    def __init__(self, agent_id: str, hmac_secret: str, base_url: str = ...): ...
    def spend_request(self, req: SpendRequest) -> SpendResponse: ...
    def get_spend_status(self, request_id: str) -> SpendResponse: ...
```

### Exception Classes

```python
class AgentShieldError(Exception): ...          # base

class AgentShieldBlockedError(AgentShieldError): ...
# Raised on 403 — hard deny. Do not retry.
# Docs: "Verdict is MALICIOUS — do not retry"

class AgentShieldAuthError(AgentShieldError): ...
# Raised on 401 — bad credentials. Rotate hmac_secret.

class AgentShieldAPIError(AgentShieldError):
# Raised on other 4xx/5xx.
    status_code: int
    message: str
```

---

## HMAC Signing — Canonical Format

The signing format is not documented in the PyPI package at all. Here is what the v2 backend actually verifies (from `app/core/security.py`):

```python
import hashlib, hmac, json
from datetime import datetime, timezone

body_json = json.dumps(body, separators=(",", ":"))
timestamp = datetime.now(timezone.utc).isoformat()
body_hash = hashlib.sha256(body_json.encode()).hexdigest()

canonical = "\n".join([
    "POST",
    "/v1/spend-request",
    timestamp,
    body_hash,
    agent_id,
])

signature = hmac.new(
    hmac_secret.encode(),
    canonical.encode(),
    hashlib.sha256,
).hexdigest()
```

Required headers:
```
x-agent-id:  agt_...
x-timestamp: 2026-05-07T12:34:56.789Z   (ISO 8601, within ±300s of server)
x-signature: sha256=<hex>               (note the "sha256=" prefix)
```

The SDK must handle all of this internally. Agents should never need to manually sign requests.

---

## Polling Pattern (SUSPICIOUS / 202)

When `spend_request()` returns `verdict="SUSPICIOUS"`, the agent must poll:

```python
import time

result = await client.spend_request(SpendRequest(...))

if result.verdict == "SUSPICIOUS":
    for _ in range(60):
        time.sleep(5)
        status = await client.get_spend_status(result.request_id)
        if status.raw_status != "PENDING_HITL":
            if status.raw_status == "APPROVED_BY_HUMAN_EXECUTED":
                print("approved")
            else:
                print("denied or expired")
            break
```

---

## Usage Pattern (from the docs)

This is the interface agents are trying to use today and hitting `ImportError`:

```python
from agentshield import AsyncAgentShield, SpendRequest

async with AsyncAgentShield(
    agent_id="agt_...",
    hmac_secret="sk_live_...",
) as client:
    result = await client.spend_request(SpendRequest(
        agent_id="agt_...",
        declared_goal="Purchase 0.01 ETH on Coinbase",
        amount_cents=2500,
        currency="USD",
        vendor_url_or_name="coinbase.com",
        item_description="0.01 ETH spot purchase",
        asset_type="FIAT",
    ))

    if result.verdict == "SAFE":
        execute_payment()
    elif result.verdict == "SUSPICIOUS":
        status = await client.get_spend_status(result.request_id)
```

---

## Reference Implementation

A working reference implementation that replicates this interface (with correct canonical HMAC signing) is in the buying agent that discovered this gap:

- Client: `src/buying_agent/clients/shield.py`
- Integration tests: `tests/test_shield_client.py`

The reference calls the v2 REST API directly via `httpx` and passes the full integration test suite. It can be used as a starting point for the official SDK implementation.

---

## What a v2 SDK Release Needs

1. **Publish `AsyncAgentShield` and `AgentShield`** with `spend_request()` and `get_spend_status()`
2. **Publish `SpendRequest`** dataclass with all documented fields
3. **Implement canonical HMAC signing internally** — agents should pass `hmac_secret`, not sign manually
4. **Publish typed exception classes** — `AgentShieldBlockedError`, `AgentShieldAuthError`, `AgentShieldAPIError`
5. **Use `httpx` not `requests`** — async agents running on FastAPI/asyncio will block the event loop with `requests`
6. **Update PyPI** — `pip install agentshield` should install the v2 SDK, not the v0.1.x monitoring tool
