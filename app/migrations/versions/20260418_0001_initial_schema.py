"""initial schema

Revision ID: 20260418_0001
Revises:
Create Date: 2026-04-18 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260418_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("daily_budget_limit_cents", sa.Integer(), nullable=False),
        sa.Column("per_txn_auto_approve_limit_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("blocked_vendors", sa.JSON(), nullable=True),
        sa.Column("allowed_stablecoins", sa.JSON(), nullable=True),
        sa.Column("allowed_networks", sa.JSON(), nullable=True),
        sa.Column("allowed_destination_addresses", sa.JSON(), nullable=True),
        sa.Column("blocked_destination_addresses", sa.JSON(), nullable=True),
        sa.Column("hitl_phone_number", sa.String(length=64), nullable=True),
        sa.Column("hitl_phone_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hitl_primary_channel", sa.String(length=16), nullable=False),
        sa.Column("hitl_sms_fallback_high_risk", sa.Boolean(), nullable=False),
        sa.Column("hitl_required_over_cents", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id"),
    )
    op.create_index("ix_agent_agent_id", "agent", ["agent_id"], unique=False)

    op.create_table(
        "dashboardnotification",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("summary", sa.String(length=512), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("acknowledged_by", sa.String(length=128), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_dashboardnotification_agent_id",
        "dashboardnotification",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        "ix_dashboardnotification_created_at",
        "dashboardnotification",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_dashboardnotification_request_id",
        "dashboardnotification",
        ["request_id"],
        unique=False,
    )
    op.create_index(
        "ix_dashboardnotification_status",
        "dashboardnotification",
        ["status"],
        unique=False,
    )

    op.create_table(
        "pendingspend",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("verdict_snapshot", sa.JSON(), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("hitl_channel", sa.String(length=16), nullable=False),
        sa.Column("hitl_contact", sa.String(length=128), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolver_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index("ix_pendingspend_agent_id", "pendingspend", ["agent_id"], unique=False)
    op.create_index("ix_pendingspend_expires_at", "pendingspend", ["expires_at"], unique=False)
    op.create_index("ix_pendingspend_request_id", "pendingspend", ["request_id"], unique=False)

    op.create_table(
        "spendauditlog",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("declared_goal", sa.String(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("asset_type", sa.String(length=16), nullable=False),
        sa.Column("stablecoin_symbol", sa.String(length=16), nullable=True),
        sa.Column("network", sa.String(length=32), nullable=True),
        sa.Column("destination_address", sa.String(length=128), nullable=True),
        sa.Column("vendor_url_or_name", sa.String(), nullable=False),
        sa.Column("item_description", sa.String(), nullable=False),
        sa.Column("quantitative_result", sa.JSON(), nullable=True),
        sa.Column("policy_result", sa.JSON(), nullable=True),
        sa.Column("semantic_result", sa.JSON(), nullable=True),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=48), nullable=False),
        sa.Column("payment_provider", sa.String(length=32), nullable=True),
        sa.Column("payment_txn_id", sa.String(length=128), nullable=True),
        sa.Column("onchain_tx_hash", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_spendauditlog_agent_id", "spendauditlog", ["agent_id"], unique=False)
    op.create_index("ix_spendauditlog_created_at", "spendauditlog", ["created_at"], unique=False)
    op.create_index(
        "ix_spendauditlog_onchain_tx_hash",
        "spendauditlog",
        ["onchain_tx_hash"],
        unique=False,
    )
    op.create_index("ix_spendauditlog_request_id", "spendauditlog", ["request_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_spendauditlog_request_id", table_name="spendauditlog")
    op.drop_index("ix_spendauditlog_onchain_tx_hash", table_name="spendauditlog")
    op.drop_index("ix_spendauditlog_created_at", table_name="spendauditlog")
    op.drop_index("ix_spendauditlog_agent_id", table_name="spendauditlog")
    op.drop_table("spendauditlog")

    op.drop_index("ix_pendingspend_request_id", table_name="pendingspend")
    op.drop_index("ix_pendingspend_expires_at", table_name="pendingspend")
    op.drop_index("ix_pendingspend_agent_id", table_name="pendingspend")
    op.drop_table("pendingspend")

    op.drop_index("ix_dashboardnotification_status", table_name="dashboardnotification")
    op.drop_index("ix_dashboardnotification_request_id", table_name="dashboardnotification")
    op.drop_index("ix_dashboardnotification_created_at", table_name="dashboardnotification")
    op.drop_index("ix_dashboardnotification_agent_id", table_name="dashboardnotification")
    op.drop_table("dashboardnotification")

    op.drop_index("ix_agent_agent_id", table_name="agent")
    op.drop_table("agent")

