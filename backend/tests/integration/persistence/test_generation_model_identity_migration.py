from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from nexus.infrastructure.persistence.models.conversation import (
    Conversation as ConversationModel,
)
from nexus.infrastructure.persistence.models.message import Message as MessageModel
from nexus.infrastructure.persistence.models.organization import Organization
from nexus.infrastructure.persistence.models.user import User

TIMESTAMP = datetime(2026, 1, 1, tzinfo=UTC)


def test_generation_model_identity_migration_round_trip(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    command.upgrade(config, "20260929_0013")

    organization_public_id = uuid4()
    user_public_id = uuid4()
    conversation_public_id = uuid4()
    message_public_id = uuid4()
    legacy_generation_public_id = uuid4()

    with Session(engine) as session:
        organization = Organization(
            public_id=organization_public_id,
            name="Migration Organization",
            slug=f"migration-{uuid4().hex[:12]}",
            status="active",
        )
        user = User(
            public_id=user_public_id,
            organization=organization,
            email=f"{uuid4().hex}@example.com",
            status="active",
        )
        session.add(user)
        session.flush()

        conversation = ConversationModel(
            public_id=conversation_public_id,
            organization_id=organization.id,
            created_by_user_id=user.id,
            workspace_public_id=None,
            project_public_id=None,
            title="Migration Conversation",
            created_at=TIMESTAMP,
            updated_at=TIMESTAMP,
        )
        session.add(conversation)
        session.flush()

        message = MessageModel(
            public_id=message_public_id,
            organization_id=organization.id,
            conversation_id=conversation.id,
            role="user",
            content="Legacy request",
            created_at=TIMESTAMP,
        )
        session.add(message)
        session.flush()

        session.execute(
            text(
                """
                INSERT INTO generations (
                    public_id,
                    organization_id,
                    conversation_id,
                    user_message_id,
                    model,
                    status,
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    started_at,
                    completed_at,
                    error_kind
                )
                VALUES (
                    :public_id,
                    :organization_id,
                    :conversation_id,
                    :user_message_id,
                    :model,
                    'failed',
                    0,
                    0,
                    0,
                    :started_at,
                    :completed_at,
                    'migration_test'
                )
                """
            ),
            {
                "public_id": legacy_generation_public_id,
                "organization_id": organization.id,
                "conversation_id": conversation.id,
                "user_message_id": message.id,
                "model": "legacy-provider-model",
                "started_at": TIMESTAMP,
                "completed_at": TIMESTAMP,
            },
        )
        session.commit()

    command.upgrade(config, "20260929_0014")

    with engine.connect() as connection:
        legacy = (
            connection.execute(
                text(
                    """
                    SELECT model, configured_model_public_id
                    FROM generations
                    WHERE public_id = :public_id
                    """
                ),
                {"public_id": legacy_generation_public_id},
            )
            .mappings()
            .one()
        )

    assert legacy["model"] == "legacy-provider-model"
    assert legacy["configured_model_public_id"] is None

    configured_model_public_id = uuid4()
    new_generation_public_id = uuid4()

    with engine.begin() as connection:
        references = (
            connection.execute(
                text(
                    """
                    SELECT
                        organizations.id AS organization_id,
                        conversations.id AS conversation_id,
                        messages.id AS user_message_id
                    FROM organizations
                    JOIN conversations
                      ON conversations.organization_id = organizations.id
                    JOIN messages
                      ON messages.organization_id = organizations.id
                     AND messages.conversation_id = conversations.id
                    WHERE organizations.public_id = :organization_public_id
                      AND conversations.public_id = :conversation_public_id
                      AND messages.public_id = :message_public_id
                    """
                ),
                {
                    "organization_public_id": organization_public_id,
                    "conversation_public_id": conversation_public_id,
                    "message_public_id": message_public_id,
                },
            )
            .mappings()
            .one()
        )
        connection.execute(
            text(
                """
                INSERT INTO generations (
                    public_id,
                    organization_id,
                    conversation_id,
                    user_message_id,
                    model,
                    configured_model_public_id,
                    status,
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    started_at,
                    completed_at,
                    error_kind
                )
                VALUES (
                    :public_id,
                    :organization_id,
                    :conversation_id,
                    :user_message_id,
                    NULL,
                    :configured_model_public_id,
                    'failed',
                    0,
                    0,
                    0,
                    :started_at,
                    :completed_at,
                    'migration_test'
                )
                """
            ),
            {
                "public_id": new_generation_public_id,
                "organization_id": references["organization_id"],
                "conversation_id": references["conversation_id"],
                "user_message_id": references["user_message_id"],
                "configured_model_public_id": configured_model_public_id,
                "started_at": TIMESTAMP,
                "completed_at": TIMESTAMP,
            },
        )

    command.downgrade(config, "20260929_0013")

    with engine.connect() as connection:
        rows = {
            row["public_id"]: row["model"]
            for row in connection.execute(
                text(
                    """
                    SELECT public_id, model
                    FROM generations
                    WHERE public_id IN (:legacy_public_id, :new_public_id)
                    """
                ),
                {
                    "legacy_public_id": legacy_generation_public_id,
                    "new_public_id": new_generation_public_id,
                },
            ).mappings()
        }
        model_nullable = connection.scalar(
            text(
                """
                SELECT is_nullable
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'generations'
                  AND column_name = 'model'
                """
            )
        )
        configured_column_count = connection.scalar(
            text(
                """
                SELECT count(*)
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'generations'
                  AND column_name = 'configured_model_public_id'
                """
            )
        )
        legacy_constraint_count = connection.scalar(
            text(
                """
                SELECT count(*)
                FROM pg_constraint
                WHERE conname = 'ck_generations_model_nonblank'
                  AND conrelid = 'generations'::regclass
                """
            )
        )

    assert rows[legacy_generation_public_id] == "legacy-provider-model"
    assert rows[new_generation_public_id] == str(configured_model_public_id)
    assert model_nullable == "NO"
    assert configured_column_count == 0
    assert legacy_constraint_count == 1

    with Session(engine) as session, pytest.raises(IntegrityError):
        session.execute(
            text(
                """
                INSERT INTO generations (
                    public_id,
                    organization_id,
                    conversation_id,
                    user_message_id,
                    model,
                    status,
                    input_tokens,
                    output_tokens,
                    total_tokens
                )
                SELECT
                    :public_id,
                    organization_id,
                    conversation_id,
                    user_message_id,
                    '   ',
                    'failed',
                    0,
                    0,
                    0
                FROM generations
                WHERE public_id = :source_public_id
                """
            ),
            {
                "public_id": uuid4(),
                "source_public_id": legacy_generation_public_id,
            },
        )
        session.commit()
