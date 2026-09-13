"""add provenance and replay counters to spend audit log

Revision ID: 20260913_0008
Revises: 20260913_0007
Create Date: 2026-09-13

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260913_0008"
down_revision: str | Sequence[str] | None = "20260913_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("spendauditlog", sa.Column("engine_provenance", sa.JSON(), nullable=True))
    op.add_column(
        "spendauditlog",
        sa.Column("idempotency_replay_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "spendauditlog",
        sa.Column("last_replayed_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("spendauditlog", "last_replayed_at")
    op.drop_column("spendauditlog", "idempotency_replay_count")
    op.drop_column("spendauditlog", "engine_provenance")
