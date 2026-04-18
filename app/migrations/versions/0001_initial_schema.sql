-- Initial AgentShield schema for PostgreSQL

CREATE TABLE IF NOT EXISTS agent (
    id UUID PRIMARY KEY,
    agent_id VARCHAR(128) UNIQUE NOT NULL,
    display_name VARCHAR(128) NOT NULL,
    status VARCHAR(16) NOT NULL,
    daily_budget_limit_cents INTEGER NOT NULL,
    per_txn_auto_approve_limit_cents INTEGER NOT NULL,
    currency VARCHAR(3) NOT NULL,
    blocked_vendors JSONB NOT NULL,
    allowed_stablecoins JSONB NOT NULL,
    allowed_networks JSONB NOT NULL,
    allowed_destination_addresses JSONB NOT NULL,
    blocked_destination_addresses JSONB NOT NULL,
    hitl_phone_number VARCHAR(64),
    hitl_phone_verified_at TIMESTAMPTZ,
    hitl_primary_channel VARCHAR(16) NOT NULL DEFAULT 'dashboard',
    hitl_sms_fallback_high_risk BOOLEAN NOT NULL DEFAULT TRUE,
    hitl_required_over_cents INTEGER,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_agent_agent_id ON agent (agent_id);

CREATE TABLE IF NOT EXISTS spendauditlog (
    id UUID PRIMARY KEY,
    request_id VARCHAR(64) NOT NULL,
    agent_id VARCHAR(128) NOT NULL,
    declared_goal TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    currency VARCHAR(3) NOT NULL,
    asset_type VARCHAR(16) NOT NULL,
    stablecoin_symbol VARCHAR(16),
    network VARCHAR(32),
    destination_address VARCHAR(128),
    vendor_url_or_name TEXT NOT NULL,
    item_description TEXT NOT NULL,
    quantitative_result JSONB NOT NULL,
    policy_result JSONB NOT NULL,
    semantic_result JSONB NOT NULL,
    verdict VARCHAR(16) NOT NULL,
    status VARCHAR(48) NOT NULL,
    payment_provider VARCHAR(32),
    payment_txn_id VARCHAR(128),
    onchain_tx_hash VARCHAR(256),
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_spendauditlog_request_id ON spendauditlog (request_id);
CREATE INDEX IF NOT EXISTS ix_spendauditlog_agent_id ON spendauditlog (agent_id);
CREATE INDEX IF NOT EXISTS ix_spendauditlog_created_at ON spendauditlog (created_at);
CREATE INDEX IF NOT EXISTS ix_spendauditlog_onchain_tx_hash ON spendauditlog (onchain_tx_hash);

CREATE TABLE IF NOT EXISTS pendingspend (
    id UUID PRIMARY KEY,
    request_id VARCHAR(64) UNIQUE NOT NULL,
    agent_id VARCHAR(128) NOT NULL,
    payload_json JSONB NOT NULL,
    verdict_snapshot JSONB NOT NULL,
    state VARCHAR(32) NOT NULL,
    hitl_channel VARCHAR(16) NOT NULL,
    hitl_contact VARCHAR(128),
    expires_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ,
    resolver_id VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_pendingspend_request_id ON pendingspend (request_id);
CREATE INDEX IF NOT EXISTS ix_pendingspend_agent_id ON pendingspend (agent_id);
CREATE INDEX IF NOT EXISTS ix_pendingspend_expires_at ON pendingspend (expires_at);

CREATE TABLE IF NOT EXISTS dashboardnotification (
    id UUID PRIMARY KEY,
    request_id VARCHAR(64) NOT NULL,
    agent_id VARCHAR(128) NOT NULL,
    category VARCHAR(32) NOT NULL,
    priority VARCHAR(16) NOT NULL,
    status VARCHAR(16) NOT NULL,
    summary VARCHAR(512) NOT NULL,
    payload_json JSONB NOT NULL,
    acknowledged_by VARCHAR(128),
    acknowledged_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_dashboardnotification_request_id ON dashboardnotification (request_id);
CREATE INDEX IF NOT EXISTS ix_dashboardnotification_agent_id ON dashboardnotification (agent_id);
CREATE INDEX IF NOT EXISTS ix_dashboardnotification_status ON dashboardnotification (status);
CREATE INDEX IF NOT EXISTS ix_dashboardnotification_created_at ON dashboardnotification (created_at);

