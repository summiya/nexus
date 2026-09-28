from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError

PREVIOUS_HEAD = "20260926_0011"
VALIDATION_PREVIOUS_HEAD = "20260928_0012"


def _organization(connection: sa.Connection, slug: str) -> int:
    return connection.execute(
        text(
            """
            INSERT INTO organizations (public_id, name, slug, status, settings_json)
            VALUES (:public_id, :name, :slug, 'active', '{}'::jsonb)
            RETURNING id
            """
        ),
        {
            "public_id": uuid.uuid4(),
            "name": slug,
            "slug": slug,
        },
    ).scalar_one()


def _provider(
    connection: sa.Connection,
    *,
    organization_id: int,
    display_name: str,
    credential_reference: uuid.UUID | None = None,
) -> int:
    return connection.execute(
        text(
            """
            INSERT INTO model_providers (
                public_id, organization_id, provider_type, display_name,
                settings_json, credential_reference, enabled
            ) VALUES (
                :public_id, :organization_id, 'openai', :display_name,
                '{}'::jsonb, :credential_reference, true
            ) RETURNING id
            """
        ),
        {
            "public_id": uuid.uuid4(),
            "organization_id": organization_id,
            "display_name": display_name,
            "credential_reference": credential_reference,
        },
    ).scalar_one()


def _model(
    connection: sa.Connection,
    *,
    organization_id: int,
    provider_id: int,
    model_type: str = "chat",
    capabilities: list[str] | None = None,
    embedding_dimension: int | None = None,
    provider_model_name: str = "gpt-test",
    display_name: str = "Test Model",
) -> int:
    return connection.execute(
        text(
            """
            INSERT INTO configured_models (
                public_id, organization_id, provider_id, provider_model_name,
                display_name, model_type, capabilities, embedding_dimension,
                enabled
            ) VALUES (
                :public_id, :organization_id, :provider_id,
                :provider_model_name, :display_name, :model_type,
                :capabilities, :embedding_dimension, true
            ) RETURNING id
            """
        ),
        {
            "public_id": uuid.uuid4(),
            "organization_id": organization_id,
            "provider_id": provider_id,
            "provider_model_name": provider_model_name,
            "display_name": display_name,
            "model_type": model_type,
            "capabilities": capabilities or [],
            "embedding_dimension": embedding_dimension,
        },
    ).scalar_one()


def _expect_integrity(
    connection: sa.Connection,
    operation: Callable[[], object],
) -> None:
    savepoint = connection.begin_nested()
    with pytest.raises(IntegrityError):
        operation()
    savepoint.rollback()


def test_upgrade_creates_tenant_safe_model_provider_schema(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    command.upgrade(config, "head")
    inspector = inspect(engine)

    assert {
        "model_providers",
        "configured_models",
        "organization_model_defaults",
    }.issubset(inspector.get_table_names())
    provider_indexes = {
        index["name"]: index for index in inspector.get_indexes("model_providers")
    }
    assert provider_indexes["uq_model_providers_credential_reference_not_null"][
        "unique"
    ]
    model_foreign_keys = {
        constraint["name"]: constraint
        for constraint in inspector.get_foreign_keys("configured_models")
    }
    assert model_foreign_keys["fk_configured_models_organization_provider"][
        "constrained_columns"
    ] == ["organization_id", "provider_id"]
    default_foreign_keys = {
        constraint["name"]: constraint
        for constraint in inspector.get_foreign_keys("organization_model_defaults")
    }
    assert default_foreign_keys["fk_organization_model_defaults_tenant_model"][
        "constrained_columns"
    ] == [
        "organization_id",
        "model_type",
        "configured_model_id",
    ]


def test_validation_migration_defaults_existing_providers_to_unvalidated(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    command.upgrade(config, VALIDATION_PREVIOUS_HEAD)
    with engine.begin() as connection:
        organization_id = _organization(connection, "validation-migration")
        provider_id = _provider(
            connection,
            organization_id=organization_id,
            display_name="Existing provider",
        )

    command.upgrade(config, "head")

    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT validation_status, last_validated_at "
                "FROM model_providers WHERE id = :provider_id"
            ),
            {"provider_id": provider_id},
        ).one()
        assert row.validation_status == "unvalidated"
        assert row.last_validated_at is None


def test_validation_constraints_reject_invalid_status_timestamp_combinations(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    command.upgrade(config, "head")
    with engine.begin() as connection:
        organization_id = _organization(connection, "validation-constraints")
        provider_id = _provider(
            connection,
            organization_id=organization_id,
            display_name="Provider",
        )
        _expect_integrity(
            connection,
            lambda: connection.execute(
                text(
                    "UPDATE model_providers SET validation_status = 'invalid' "
                    "WHERE id = :provider_id"
                ),
                {"provider_id": provider_id},
            ),
        )
        _expect_integrity(
            connection,
            lambda: connection.execute(
                text(
                    "UPDATE model_providers SET validation_status = 'valid' "
                    "WHERE id = :provider_id"
                ),
                {"provider_id": provider_id},
            ),
        )


def test_validation_migration_downgrade_removes_validation_columns(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    command.upgrade(config, "head")

    command.downgrade(config, VALIDATION_PREVIOUS_HEAD)

    columns = {
        column["name"] for column in inspect(engine).get_columns("model_providers")
    }
    assert "validation_status" not in columns
    assert "last_validated_at" not in columns


def test_database_rejects_reused_non_null_credential_reference(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    command.upgrade(config, "head")
    with engine.begin() as connection:
        organization_id = _organization(connection, "credential-unique")
        reference = uuid.uuid4()
        _provider(
            connection,
            organization_id=organization_id,
            display_name="Primary",
            credential_reference=reference,
        )
        _expect_integrity(
            connection,
            lambda: _provider(
                connection,
                organization_id=organization_id,
                display_name="Secondary",
                credential_reference=reference,
            ),
        )


def test_provider_constraints_allow_same_type_but_reject_invalid_rows(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    command.upgrade(config, "head")
    with engine.begin() as connection:
        organization_id = _organization(connection, "provider-constraints")
        _provider(
            connection,
            organization_id=organization_id,
            display_name="Production",
        )
        _provider(
            connection,
            organization_id=organization_id,
            display_name="Testing",
        )
        _expect_integrity(
            connection,
            lambda: _provider(
                connection,
                organization_id=organization_id,
                display_name="Production",
            ),
        )
        _expect_integrity(
            connection,
            lambda: connection.execute(
                text(
                    """
                    INSERT INTO model_providers (
                        public_id, organization_id, provider_type,
                        display_name, settings_json, enabled
                    ) VALUES (
                        :public_id, :organization_id, 'unknown',
                        'Invalid', '{}'::jsonb, true
                    )
                    """
                ),
                {"public_id": uuid.uuid4(), "organization_id": organization_id},
            ),
        )
        _expect_integrity(
            connection,
            lambda: connection.execute(
                text(
                    """
                    INSERT INTO model_providers (
                        public_id, organization_id, provider_type,
                        display_name, settings_json, enabled
                    ) VALUES (
                        :public_id, :organization_id, 'openai',
                        'Secret Shape', '{"api_key":"forbidden"}'::jsonb, true
                    )
                    """
                ),
                {"public_id": uuid.uuid4(), "organization_id": organization_id},
            ),
        )


@pytest.mark.parametrize(
    ("model_type", "capabilities", "embedding_dimension", "display_name"),
    [
        ("unknown", [], None, "Invalid type"),
        ("chat", ["unknown"], None, "Invalid capability"),
        ("embedding", ["streaming"], 1536, "Embedding capability"),
        ("reranker", ["tools"], None, "Reranker capability"),
        ("embedding", [], None, "Missing dimension"),
        ("embedding", [], 0, "Invalid dimension"),
        ("chat", [], 1536, "Chat dimension"),
        ("reranker", [], 128, "Reranker dimension"),
        ("chat", [], None, "   "),
    ],
)
def test_model_constraints_reject_invalid_rows(
    migrated_database: tuple[Config, Engine],
    model_type: str,
    capabilities: list[str],
    embedding_dimension: int | None,
    display_name: str,
) -> None:
    config, engine = migrated_database
    command.upgrade(config, "head")
    with engine.begin() as connection:
        organization_id = _organization(connection, f"invalid-{uuid.uuid4().hex[:8]}")
        provider_id = _provider(
            connection,
            organization_id=organization_id,
            display_name="Provider",
        )
        _expect_integrity(
            connection,
            lambda: _model(
                connection,
                organization_id=organization_id,
                provider_id=provider_id,
                model_type=model_type,
                capabilities=capabilities,
                embedding_dimension=embedding_dimension,
                display_name=display_name,
            ),
        )


def test_database_rejects_cross_tenant_provider_and_default_references(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    command.upgrade(config, "head")
    with engine.begin() as connection:
        organization_a = _organization(connection, "tenant-a")
        organization_b = _organization(connection, "tenant-b")
        provider_a = _provider(
            connection,
            organization_id=organization_a,
            display_name="Provider A",
        )
        model_a = _model(
            connection,
            organization_id=organization_a,
            provider_id=provider_a,
            capabilities=["streaming"],
        )
        _expect_integrity(
            connection,
            lambda: _model(
                connection,
                organization_id=organization_b,
                provider_id=provider_a,
                capabilities=["streaming"],
            ),
        )
        _expect_integrity(
            connection,
            lambda: connection.execute(
                text(
                    """
                    INSERT INTO organization_model_defaults (
                        organization_id, model_type, configured_model_id
                    ) VALUES (:organization_id, 'chat', :model_id)
                    """
                ),
                {"organization_id": organization_b, "model_id": model_a},
            ),
        )
        _expect_integrity(
            connection,
            lambda: connection.execute(
                text(
                    """
                    INSERT INTO organization_model_defaults (
                        organization_id, model_type, configured_model_id
                    ) VALUES (:organization_id, 'embedding', :model_id)
                    """
                ),
                {"organization_id": organization_a, "model_id": model_a},
            ),
        )


def test_database_restricts_provider_and_default_model_deletion(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    command.upgrade(config, "head")
    with engine.begin() as connection:
        organization_id = _organization(connection, "delete-restrict")
        provider_id = _provider(
            connection,
            organization_id=organization_id,
            display_name="Provider",
        )
        model_id = _model(
            connection,
            organization_id=organization_id,
            provider_id=provider_id,
            capabilities=["streaming"],
        )
        connection.execute(
            text(
                """
                INSERT INTO organization_model_defaults (
                    organization_id, model_type, configured_model_id
                ) VALUES (:organization_id, 'chat', :model_id)
                """
            ),
            {"organization_id": organization_id, "model_id": model_id},
        )
        _expect_integrity(
            connection,
            lambda: connection.execute(
                text("DELETE FROM model_providers WHERE id = :provider_id"),
                {"provider_id": provider_id},
            ),
        )
        _expect_integrity(
            connection,
            lambda: connection.execute(
                text("DELETE FROM configured_models WHERE id = :model_id"),
                {"model_id": model_id},
            ),
        )


def test_migration_downgrade_removes_schema_and_seeded_permissions(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    command.upgrade(config, "head")
    command.downgrade(config, PREVIOUS_HEAD)

    inspector = inspect(engine)
    assert "model_providers" not in inspector.get_table_names()
    assert "configured_models" not in inspector.get_table_names()
    assert "organization_model_defaults" not in inspector.get_table_names()
    with engine.connect() as connection:
        assert (
            connection.scalar(
                text(
                    """
                    SELECT count(*) FROM permissions
                    WHERE key IN ('model_providers.read', 'model_providers.manage')
                    """
                )
            )
            == 0
        )


def test_upgrade_grants_new_permissions_to_system_administrator_only(
    migrated_database: tuple[Config, Engine],
) -> None:
    config, engine = migrated_database
    command.upgrade(config, PREVIOUS_HEAD)
    with engine.begin() as connection:
        organization_id = _organization(connection, "permission-grant")
        administrator_id = connection.execute(
            text(
                """
                INSERT INTO roles (
                    public_id, organization_id, name, is_system
                ) VALUES (:public_id, :organization_id, 'Administrator', true)
                RETURNING id
                """
            ),
            {"public_id": uuid.uuid4(), "organization_id": organization_id},
        ).scalar_one()
        custom_role_id = connection.execute(
            text(
                """
                INSERT INTO roles (
                    public_id, organization_id, name, is_system
                ) VALUES (:public_id, :organization_id, 'Model Operator', false)
                RETURNING id
                """
            ),
            {"public_id": uuid.uuid4(), "organization_id": organization_id},
        ).scalar_one()

    command.upgrade(config, "head")
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT role_permissions.role_id, permissions.key
                FROM role_permissions
                JOIN permissions ON permissions.id = role_permissions.permission_id
                WHERE permissions.key LIKE 'model_providers.%'
                """
            )
        ).all()

    assert set(rows) == {
        (administrator_id, "model_providers.read"),
        (administrator_id, "model_providers.manage"),
    }
    assert all(role_id != custom_role_id for role_id, _ in rows)
