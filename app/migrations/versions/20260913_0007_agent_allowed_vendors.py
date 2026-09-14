"""add allowed_vendors to agent

Revision ID: 20260913_0007
Revises: 923589d9f23e
Create Date: 2026-09-13

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260913_0007"
down_revision: str | Sequence[str] | None = "923589d9f23e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent", sa.Column("allowed_vendors", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent", "allowed_vendors")
