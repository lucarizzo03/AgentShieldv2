"""add per-agent hmac secret fields

Revision ID: 20260420_0002
Revises: 20260418_0001
Create Date: 2026-04-20 00:02:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260420_0002"
down_revision: Union[str, Sequence[str], None] = "20260418_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent", sa.Column("hmac_secret", sa.String(length=256), nullable=True))
    op.add_column("agent", sa.Column("hmac_secret_rotated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("agent", "hmac_secret_rotated_at")
    op.drop_column("agent", "hmac_secret")
