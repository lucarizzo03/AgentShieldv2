"""add users ownership and agent activity tables

Revision ID: 20260501_0004
Revises: 20260430_0003
Create Date: 2026-05-01 00:04:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260501_0004"
down_revision: Union[str, Sequence[str], None] = "20260430_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("cognito_sub", sa.String(length=128), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cognito_sub"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_cognito_sub", "users", ["cognito_sub"], unique=False)
    op.create_index("ix_users_email", "users", ["email"], unique=False)

    op.add_column("agent", sa.Column("owner_user_id", sa.Uuid(), nullable=True))
    op.create_index("ix_agent_owner_user_id", "agent", ["owner_user_id"], unique=False)
    op.create_foreign_key("fk_agent_owner_user_id_users", "agent", "users", ["owner_user_id"], ["id"])

    op.create_table(
        "agent_activity",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.agent_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_activity_agent_id", "agent_activity", ["agent_id"], unique=False)
    op.create_index("ix_agent_activity_user_id", "agent_activity", ["user_id"], unique=False)
    op.create_index("ix_agent_activity_event_type", "agent_activity", ["event_type"], unique=False)
    op.create_index("ix_agent_activity_created_at", "agent_activity", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_agent_activity_created_at", table_name="agent_activity")
    op.drop_index("ix_agent_activity_event_type", table_name="agent_activity")
    op.drop_index("ix_agent_activity_user_id", table_name="agent_activity")
    op.drop_index("ix_agent_activity_agent_id", table_name="agent_activity")
    op.drop_table("agent_activity")

    op.drop_constraint("fk_agent_owner_user_id_users", "agent", type_="foreignkey")
    op.drop_index("ix_agent_owner_user_id", table_name="agent")
    op.drop_column("agent", "owner_user_id")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_cognito_sub", table_name="users")
    op.drop_table("users")
