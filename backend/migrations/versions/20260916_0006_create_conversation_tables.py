"""Create Conversation persistence tables.

Revision ID: 20260916_0006
Revises: 20260916_0005
Create Date: 2026-09-18 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260916_0006"
down_revision: str | None = "20260916_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("workspace_public_id", sa.Uuid(), nullable=True),
        sa.Column("project_public_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_conversations_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_conversations_creator_organization_users",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.CheckConstraint(
            "project_public_id IS NULL OR workspace_public_id IS NOT NULL",
            name="ck_conversations_project_requires_workspace",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
        sa.UniqueConstraint("public_id", name="uq_conversations_public_id"),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            name="uq_conversations_id_organization_id",
        ),
    )
    op.create_index(
        "ix_conversations_creator_created_at",
        "conversations",
        ["organization_id", "created_by_user_id", "created_at", "id"],
    )
    op.create_index(
        "ix_conversations_workspace_created_at",
        "conversations",
        ["organization_id", "workspace_public_id", "created_at", "id"],
    )
    op.create_index(
        "ix_conversations_project_created_at",
        "conversations",
        ["organization_id", "project_public_id", "created_at", "id"],
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "organization_id"],
            ["conversations.id", "conversations.organization_id"],
            name="fk_messages_conversation_organization_conversations",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "role IN ('system', 'user', 'assistant')",
            name="ck_messages_role",
        ),
        sa.CheckConstraint(
            "content ~ '\\S'",
            name="ck_messages_content_nonblank",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
        sa.UniqueConstraint("public_id", name="uq_messages_public_id"),
        sa.UniqueConstraint(
            "id",
            "conversation_id",
            "organization_id",
            name="uq_messages_id_conversation_organization",
        ),
    )
    op.create_index(
        "ix_messages_conversation_created_at",
        "messages",
        ["organization_id", "conversation_id", "created_at", "id"],
    )

    op.create_table(
        "generations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", sa.BigInteger(), nullable=False),
        sa.Column("user_message_id", sa.BigInteger(), nullable=False),
        sa.Column("assistant_message_id", sa.BigInteger(), nullable=True),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("finish_reason", sa.String(length=32), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_kind", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "organization_id"],
            ["conversations.id", "conversations.organization_id"],
            name="fk_generations_conversation_organization_conversations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_message_id", "conversation_id", "organization_id"],
            ["messages.id", "messages.conversation_id", "messages.organization_id"],
            name="fk_generations_user_message_scope_messages",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.ForeignKeyConstraint(
            ["assistant_message_id", "conversation_id", "organization_id"],
            ["messages.id", "messages.conversation_id", "messages.organization_id"],
            name="fk_generations_assistant_message_scope_messages",
            ondelete="NO ACTION",
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_generations_status",
        ),
        sa.CheckConstraint(
            "finish_reason IS NULL OR finish_reason IN "
            "('stop', 'length', 'tool_calls', 'content_filter', 'unknown')",
            name="ck_generations_finish_reason",
        ),
        sa.CheckConstraint(
            "btrim(model) <> ''",
            name="ck_generations_model_nonblank",
        ),
        sa.CheckConstraint(
            "input_tokens >= 0",
            name="ck_generations_input_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "output_tokens >= 0",
            name="ck_generations_output_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "total_tokens >= 0",
            name="ck_generations_total_tokens_nonnegative",
        ),
        sa.CheckConstraint(
            "error_kind IS NULL OR btrim(error_kind) <> ''",
            name="ck_generations_error_kind_nonblank",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_generations"),
        sa.UniqueConstraint("public_id", name="uq_generations_public_id"),
    )
    op.create_index(
        "ix_generations_conversation_created_at",
        "generations",
        ["organization_id", "conversation_id", "created_at", "id"],
    )
    op.create_index(
        "ix_generations_user_message",
        "generations",
        ["organization_id", "conversation_id", "user_message_id"],
    )
    op.create_index(
        "ix_generations_assistant_message",
        "generations",
        ["organization_id", "conversation_id", "assistant_message_id"],
        postgresql_where=sa.text("assistant_message_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_generations_assistant_message", table_name="generations")
    op.drop_index("ix_generations_user_message", table_name="generations")
    op.drop_index("ix_generations_conversation_created_at", table_name="generations")
    op.drop_table("generations")

    op.drop_index("ix_messages_conversation_created_at", table_name="messages")
    op.drop_table("messages")

    op.drop_index("ix_conversations_project_created_at", table_name="conversations")
    op.drop_index("ix_conversations_workspace_created_at", table_name="conversations")
    op.drop_index("ix_conversations_creator_created_at", table_name="conversations")
    op.drop_table("conversations")
