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
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    existing_tables = set(inspector.get_table_names())

    if "users" not in existing_tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("auth_subject", sa.String(length=128), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("display_name", sa.String(length=128), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("auth_subject"),
            sa.UniqueConstraint("email"),
        )

    users_indexes = {idx["name"] for idx in inspector.get_indexes("users")}
    if "ix_users_auth_subject" not in users_indexes:
        op.create_index("ix_users_auth_subject", "users", ["auth_subject"], unique=False)
    if "ix_users_email" not in users_indexes:
        op.create_index("ix_users_email", "users", ["email"], unique=False)

    agent_columns = {col["name"] for col in inspector.get_columns("agent")}
    if "owner_user_id" not in agent_columns:
        op.add_column("agent", sa.Column("owner_user_id", sa.Uuid(), nullable=True))

    agent_indexes = {idx["name"] for idx in inspector.get_indexes("agent")}
    if "ix_agent_owner_user_id" not in agent_indexes:
        op.create_index("ix_agent_owner_user_id", "agent", ["owner_user_id"], unique=False)

    agent_fks = {fk["name"] for fk in inspector.get_foreign_keys("agent")}
    if "fk_agent_owner_user_id_users" not in agent_fks:
        op.create_foreign_key("fk_agent_owner_user_id_users", "agent", "users", ["owner_user_id"], ["id"])

    if "agent_activity" not in existing_tables:
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

    activity_indexes = {idx["name"] for idx in inspector.get_indexes("agent_activity")}
    if "ix_agent_activity_agent_id" not in activity_indexes:
        op.create_index("ix_agent_activity_agent_id", "agent_activity", ["agent_id"], unique=False)
    if "ix_agent_activity_user_id" not in activity_indexes:
        op.create_index("ix_agent_activity_user_id", "agent_activity", ["user_id"], unique=False)
    if "ix_agent_activity_event_type" not in activity_indexes:
        op.create_index("ix_agent_activity_event_type", "agent_activity", ["event_type"], unique=False)
    if "ix_agent_activity_created_at" not in activity_indexes:
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
    op.drop_index("ix_users_auth_subject", table_name="users")
    op.drop_table("users")
