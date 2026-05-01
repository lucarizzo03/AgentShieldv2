"""add hitl_channel and hitl_contact to pending_spend

Revision ID: 20260430_0003
Revises: 20260420_0002
Create Date: 2026-04-30 00:03:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260430_0003"
down_revision: Union[str, Sequence[str], None] = "20260420_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pendingspend", sa.Column("hitl_channel", sa.String(length=32), nullable=False, server_default="email+dashboard"))
    op.add_column("pendingspend", sa.Column("hitl_contact", sa.String(length=256), nullable=True))


def downgrade() -> None:
    op.drop_column("pendingspend", "hitl_contact")
    op.drop_column("pendingspend", "hitl_channel")
