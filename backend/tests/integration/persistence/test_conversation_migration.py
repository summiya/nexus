import json
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError

from nexus.config.settings import settings

BACKEND_ROOT = Path(__file__).resolve().parents[3]
PREVIOUS_HEAD = "20260916_0005"


def normalize_postgresql_driver(database_url: str) -> str:
    url = make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


@pytest.fixture
def migrated_database() -> Iterator[tuple[Config, Engine]]:
    database_url = normalize_postgresql_driver(settings.database_url)
    database_name = f"nexus_conversation_migration_test_{uuid.uuid4().hex}"
    test_url = make_url(database_url).set(database=database_name)
    admin_engine = create_engine(database_url, isolation_level="AUTOCOMMIT")

    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    except OperationalError:
        if os.environ.get("NEXUS_REQUIRE_POSTGRES_TESTS") == "true":
            raise
        pytest.skip("PostgreSQL is not available for migration tests")

    engine = create_engine(test_url)
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.attributes["database_url"] = test_url.render_as_string(hide_password=False)

    try:
        yield config, engine
    finally:
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(
                text(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = :database_name AND pid <> pg_backend_pid()
                    """
                ),
                {"database_name": database_name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin_engine.dispose()


def upgrade(config: Config) -> None:
    command.upgrade(config, "head")


def insert_organization(connection: sa.Connection, slug: str) -> int:
    return connection.execute(
        text(
            """
            INSERT INTO organizations (
                public_id, name, slug, status, settings_json
            )
            VALUES (
                :public_id, :name, :slug, 'active', CAST(:settings_json AS JSONB)
            )
            RETURNING id
            """
        ),
        {
            "public_id": str(uuid.uuid4()),
            "name": f"Organization {slug}",
            "slug": slug,
            "settings_json": json.dumps({}),
        },
    ).scalar_one()


def insert_user(
    connection: sa.Connection,
    organization_id: int,
    email: str,
) -> int:
    return connection.execute(
        text(
            """
            INSERT INTO users (public_id, organization_id, email, status)
            VALUES (:public_id, :organization_id, :email, 'active')
            RETURNING id
            """
        ),
        {
            "public_id": str(uuid.uuid4()),
            "organization_id": organization_id,
            "email": email,
        },
    ).scalar_one()


def insert_conversation(
    connection: sa.Connection,
    organization_id: int,
    created_by_user_id: int,
    *,
    workspace_public_id: uuid.UUID | None = None,
    project_public_id: uuid.UUID | None = None,
) -> int:
    return connection.execute(
        text(
            """
            INSERT INTO conversations (
                public_id,
                organization_id,
                created_by_user_id,
                workspace_public_id,
                project_public_id,
                title
            )
            VALUES (
                :public_id,
                :organization_id,
                :created_by_user_id,
                :workspace_public_id,
                :project_public_id,
                :title
            )
            RETURNING id
            """
        ),
        {
            "public_id": str(uuid.uuid4()),
            "organization_id": organization_id,
            "created_by_user_id": created_by_user_id,
            "workspace_public_id": (
                str(workspace_public_id) if workspace_public_id else None
            ),
            "project_public_id": (
                str(project_public_id) if project_public_id else None
            ),
            "title": "Conversation",
        },
    ).scalar_one()


def insert_message(
    connection: sa.Connection,
    organization_id: int,
    conversation_id: int,
    *,
    role: str = "user",
    content: str = "Hello",
) -> int:
    return connection.execute(
        text(
            """
            INSERT INTO messages (
                public_id, organization_id, conversation_id, role, content
            )
            VALUES (
                :public_id, :organization_id, :conversation_id, :role, :content
            )
            RETURNING id
            """
        ),
        {
            "public_id": str(uuid.uuid4()),
            "organization_id": organization_id,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
        },
    ).scalar_one()


def insert_generation(
    connection: sa.Connection,
    organization_id: int,
    conversation_id: int,
    user_message_id: int,
    *,
    assistant_message_id: int | None = None,
    model: str = "gpt-test",
    status: str = "pending",
    finish_reason: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
    error_kind: str | None = None,
) -> int:
    return connection.execute(
        text(
            """
            INSERT INTO generations (
                public_id,
                organization_id,
                conversation_id,
                user_message_id,
                assistant_message_id,
                model,
                status,
                finish_reason,
                input_tokens,
                output_tokens,
                total_tokens,
                error_kind
            )
            VALUES (
                :public_id,
                :organization_id,
                :conversation_id,
                :user_message_id,
                :assistant_message_id,
                :model,
                :status,
                :finish_reason,
                :input_tokens,
                :output_tokens,
                :total_tokens,
                :error_kind
            )
            RETURNING id
            """
        ),
        {
            "public_id": str(uuid.uuid4()),
            "organization_id": organization_id,
            "conversation_id": conversation_id,
            "user_message_id": user_message_id,
            "assistant_message_id": assistant_message_id,
            "model": model,
            "status": status,
            "finish_reason": finish_reason,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "error_kind": error_kind,
        },
    ).scalar_one()


def test_upgrade_creates_conversation_schema(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    upgrade(config)

    inspector = inspect(engine)
    assert {"conversations", "messages", "generations"}.issubset(
        set(inspector.get_table_names())
    )
    assert inspector.get_pk_constraint("conversations")["constrained_columns"] == ["id"]
    assert inspector.get_pk_constraint("messages")["constrained_columns"] == ["id"]
    assert inspector.get_pk_constraint("generations")["constrained_columns"] == ["id"]

    conversation_columns = {
        column["name"]: column for column in inspector.get_columns("conversations")
    }
    message_columns = {
        column["name"]: column for column in inspector.get_columns("messages")
    }
    generation_columns = {
        column["name"]: column for column in inspector.get_columns("generations")
    }

    assert conversation_columns["organization_id"]["nullable"] is False
    assert conversation_columns["created_by_user_id"]["nullable"] is False
    assert conversation_columns["workspace_public_id"]["nullable"] is True
    assert conversation_columns["project_public_id"]["nullable"] is True
    assert message_columns["content"]["nullable"] is False
    assert generation_columns["user_message_id"]["nullable"] is False
    assert generation_columns["assistant_message_id"]["nullable"] is True
    assert generation_columns["created_at"]["nullable"] is False
    assert generation_columns["updated_at"]["nullable"] is False

    unique_constraints = {
        constraint["name"]
        for table in ("conversations", "messages", "generations")
        for constraint in inspector.get_unique_constraints(table)
    }
    assert {
        "uq_conversations_public_id",
        "uq_conversations_id_organization_id",
        "uq_messages_public_id",
        "uq_messages_id_conversation_organization",
        "uq_generations_public_id",
    }.issubset(unique_constraints)

    index_names = {
        index["name"]
        for table in ("conversations", "messages", "generations")
        for index in inspector.get_indexes(table)
        if index.get("duplicates_constraint") is None
    }
    assert index_names == {
        "ix_conversations_creator_created_at",
        "ix_conversations_workspace_created_at",
        "ix_conversations_project_created_at",
        "ix_messages_conversation_created_at",
        "ix_generations_conversation_created_at",
    }

    foreign_keys = {
        foreign_key["name"]: foreign_key
        for table in ("conversations", "messages", "generations")
        for foreign_key in inspector.get_foreign_keys(table)
    }
    assert (
        foreign_keys["fk_conversations_organization_id_organizations"]["options"][
            "ondelete"
        ]
        == "CASCADE"
    )
    assert foreign_keys["fk_messages_conversation_organization_conversations"][
        "constrained_columns"
    ] == ["conversation_id", "organization_id"]
    assert (
        foreign_keys["fk_generations_user_message_scope_messages"]["options"].get(
            "ondelete", "NO ACTION"
        )
        == "NO ACTION"
    )
    assert (
        foreign_keys["fk_generations_assistant_message_scope_messages"]["options"].get(
            "ondelete", "NO ACTION"
        )
        == "NO ACTION"
    )


def test_valid_scopes_messages_and_generation_shapes_persist(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    upgrade(config)

    with engine.begin() as connection:
        organization_id = insert_organization(connection, "valid-scopes")
        user_id = insert_user(connection, organization_id, "creator@example.com")
        standalone_id = insert_conversation(connection, organization_id, user_id)
        workspace_id = insert_conversation(
            connection,
            organization_id,
            user_id,
            workspace_public_id=uuid.uuid4(),
        )
        project_id = insert_conversation(
            connection,
            organization_id,
            user_id,
            workspace_public_id=uuid.uuid4(),
            project_public_id=uuid.uuid4(),
        )
        standalone_message_id = insert_message(
            connection,
            organization_id,
            standalone_id,
            role="user",
            content="Standalone request",
        )
        workspace_message_id = insert_message(
            connection,
            organization_id,
            workspace_id,
            role="user",
            content="Workspace request",
        )
        user_message_id = insert_message(
            connection,
            organization_id,
            project_id,
            role="user",
            content="Generate a response",
        )
        assistant_message_id = insert_message(
            connection,
            organization_id,
            project_id,
            role="assistant",
            content="Here is the response",
        )
        insert_generation(
            connection,
            organization_id,
            standalone_id,
            standalone_message_id,
            status="pending",
        )
        insert_generation(
            connection,
            organization_id,
            project_id,
            user_message_id,
            assistant_message_id=assistant_message_id,
            status="completed",
            finish_reason="stop",
            input_tokens=4,
            output_tokens=3,
            total_tokens=7,
        )
        insert_generation(
            connection,
            organization_id,
            workspace_id,
            workspace_message_id,
            status="failed",
            error_kind="provider_unavailable",
        )
        insert_generation(
            connection,
            organization_id,
            project_id,
            user_message_id,
            status="cancelled",
        )

    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM conversations")).scalar() == 3
        )
        assert connection.execute(text("SELECT count(*) FROM messages")).scalar() == 4
        assert (
            connection.execute(text("SELECT count(*) FROM generations")).scalar() == 4
        )


def test_postgresql_rejects_invalid_conversation_and_message_rows(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    upgrade(config)

    with engine.begin() as connection:
        organization_one = insert_organization(connection, "conversation-one")
        organization_two = insert_organization(connection, "conversation-two")
        user_one = insert_user(connection, organization_one, "one@example.com")
        user_two = insert_user(connection, organization_two, "two@example.com")
        conversation_id = insert_conversation(connection, organization_one, user_one)

    with pytest.raises(IntegrityError), engine.begin() as connection:
        insert_conversation(
            connection,
            organization_one,
            user_one,
            project_public_id=uuid.uuid4(),
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        insert_conversation(connection, organization_one, user_two)

    with pytest.raises(IntegrityError), engine.begin() as connection:
        insert_message(
            connection,
            organization_two,
            conversation_id,
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        insert_message(connection, organization_one, conversation_id, role="tool")

    with pytest.raises(IntegrityError), engine.begin() as connection:
        insert_message(connection, organization_one, conversation_id, content=" \t ")


def test_postgresql_rejects_invalid_generation_references_and_values(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    upgrade(config)

    with engine.begin() as connection:
        organization_one = insert_organization(connection, "generation-one")
        organization_two = insert_organization(connection, "generation-two")
        user_one = insert_user(connection, organization_one, "one@example.com")
        user_two = insert_user(connection, organization_two, "two@example.com")
        conversation_one = insert_conversation(connection, organization_one, user_one)
        conversation_two = insert_conversation(connection, organization_one, user_one)
        conversation_other_org = insert_conversation(
            connection, organization_two, user_two
        )
        user_message_one = insert_message(
            connection, organization_one, conversation_one
        )
        user_message_two = insert_message(
            connection, organization_one, conversation_two
        )
        other_org_message = insert_message(
            connection, organization_two, conversation_other_org
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        insert_generation(
            connection,
            organization_two,
            conversation_one,
            user_message_one,
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        insert_generation(
            connection,
            organization_one,
            conversation_one,
            user_message_two,
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        insert_generation(
            connection,
            organization_one,
            conversation_one,
            other_org_message,
        )

    invalid_values = [
        {"status": "queued"},
        {"finish_reason": "provider_specific"},
        {"model": "  "},
        {"input_tokens": -1},
        {"output_tokens": -1},
        {"total_tokens": -1},
        {"error_kind": "  "},
    ]
    for values in invalid_values:
        with pytest.raises(IntegrityError), engine.begin() as connection:
            insert_generation(
                connection,
                organization_one,
                conversation_one,
                user_message_one,
                **values,
            )


def test_delete_semantics_preserve_generation_on_direct_message_delete_and_cascade_tenant(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    upgrade(config)

    with engine.begin() as connection:
        organization_id = insert_organization(connection, "delete-semantics")
        user_id = insert_user(connection, organization_id, "delete@example.com")
        conversation_id = insert_conversation(connection, organization_id, user_id)
        user_message_id = insert_message(connection, organization_id, conversation_id)
        insert_generation(
            connection,
            organization_id,
            conversation_id,
            user_message_id,
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text("DELETE FROM messages WHERE id = :message_id"),
            {"message_id": user_message_id},
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text("DELETE FROM users WHERE id = :user_id"),
            {"user_id": user_id},
        )

    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM organizations WHERE id = :organization_id"),
            {"organization_id": organization_id},
        )

    with engine.connect() as connection:
        for table in ("conversations", "messages", "generations"):
            assert (
                connection.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0
            )


def test_phase_two_downgrade_preserves_previous_schema_and_is_reversible(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    upgrade(config)

    command.downgrade(config, PREVIOUS_HEAD)
    tables_after_downgrade = set(inspect(engine).get_table_names())
    assert {"organizations", "users", "auth_sessions"}.issubset(tables_after_downgrade)
    assert not {"conversations", "messages", "generations"}.intersection(
        tables_after_downgrade
    )

    upgrade(config)
    assert {"conversations", "messages", "generations"}.issubset(
        set(inspect(engine).get_table_names())
    )
