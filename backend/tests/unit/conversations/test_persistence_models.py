from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from nexus.infrastructure.persistence.models import Conversation, Generation, Message


def test_conversation_persistence_model_defines_scope_and_tenant_constraints() -> None:
    constraints = Conversation.__table__.constraints

    assert Conversation.__tablename__ == "conversations"
    assert Conversation.__table__.c.id.primary_key is True
    assert any(
        isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_conversations_project_requires_workspace"
        for constraint in constraints
    )
    assert any(
        isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "fk_conversations_creator_organization_users"
        for constraint in constraints
    )
    assert any(
        isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_conversations_id_organization_id"
        for constraint in constraints
    )


def test_message_persistence_model_defines_tenant_safe_content_constraints() -> None:
    constraints = Message.__table__.constraints

    assert Message.__tablename__ == "messages"
    assert Message.__table__.c.id.primary_key is True
    assert any(
        isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_messages_role"
        for constraint in constraints
    )
    assert any(
        isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_messages_content_nonblank"
        for constraint in constraints
    )
    assert any(
        isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "fk_messages_conversation_organization_conversations"
        for constraint in constraints
    )
    assert any(
        isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_messages_id_conversation_organization"
        for constraint in constraints
    )


def test_generation_persistence_model_defines_usage_and_message_constraints() -> None:
    constraints = Generation.__table__.constraints
    indexes = {index.name: index for index in Generation.__table__.indexes}

    assert Generation.__tablename__ == "generations"
    assert Generation.__table__.c.id.primary_key is True
    assert any(
        isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_generations_status"
        for constraint in constraints
    )
    assert any(
        isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_generations_finish_reason"
        for constraint in constraints
    )
    assert any(
        isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "fk_generations_user_message_scope_messages"
        for constraint in constraints
    )
    assert any(
        isinstance(constraint, ForeignKeyConstraint)
        and constraint.name == "fk_generations_assistant_message_scope_messages"
        for constraint in constraints
    )
    assert indexes["ix_generations_user_message"].columns.keys() == [
        "organization_id",
        "conversation_id",
        "user_message_id",
    ]
    assert (
        indexes["ix_generations_assistant_message"]
        .dialect_options["postgresql"]["where"]
        .text
        == "assistant_message_id IS NOT NULL"
    )
    active_index = indexes["uq_generations_one_running_per_conversation"]
    assert active_index.unique is True
    assert active_index.columns.keys() == ["organization_id", "conversation_id"]
    assert active_index.dialect_options["postgresql"]["where"].text == (
        "status = 'running'"
    )
    idempotency_index = indexes["uq_generations_conversation_idempotency_key"]
    assert idempotency_index.unique is True
    assert idempotency_index.columns.keys() == [
        "organization_id",
        "conversation_id",
        "idempotency_key",
    ]
    assert idempotency_index.dialect_options["postgresql"]["where"].text == (
        "idempotency_key IS NOT NULL"
    )
