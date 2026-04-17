# AgentShield

AgentShield is a spending firewall for autonomous agents. It performs financial triangulation before any payment and enforces HITL pause/resume for suspicious requests.

## Core Features

- `POST /v1/spend-request` with SAFE/SUSPICIOUS/MALICIOUS branching
- `POST /v1/hitl/resolve/{request_id}` for human approval/deny webhook
- Stablecoin-first policy controls (token, network, destination wallet)
- Redis-backed budget and loop detection
- Immutable audit ledger in relational storage

## Local Setup

1. Copy `.env.example` to `.env`
2. Start dependencies:
   - `docker compose -f infra/docker-compose.yml up -d`
3. Run API:
   - `uvicorn app.main:app --reload`

## Notes

- Python `3.11+` is required.
- The initial SQL migration is in `app/migrations/versions/0001_initial_schema.sql`.

