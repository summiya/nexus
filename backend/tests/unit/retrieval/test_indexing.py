"""Model-neutral lifecycle invariants, without persistence or provider execution."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from itertools import product
from uuid import UUID, uuid4

import pytest

from nexus.retrieval.domain.indexing import (
    IndexingGeneration,
    IndexingStatus,
    IndexingTransitionError,
)

NOW = datetime(2026, 11, 4, tzinfo=UTC)
START = NOW + timedelta(seconds=1)
FINISH = START + timedelta(seconds=1)


def pending() -> IndexingGeneration:
    return IndexingGeneration(
        organization_public_id=uuid4(),
        document_public_id=uuid4(),
        configured_model_public_id=uuid4(),
        embedding_generation=1,
        embedding_version="input-v1",
        provider_type="future-provider",
        provider_model_name="future-model",
        embedding_dimension=768,
        created_at=NOW,
    )


def test_model_neutral_snapshot_is_immutable_and_redacted():
    generation = pending()
    assert generation.model_snapshot == (
        "input-v1",
        "future-provider",
        "future-model",
        768,
    )
    assert generation.identity[-1] == 1
    with pytest.raises(FrozenInstanceError):
        generation.embedding_dimension = 1536  # type: ignore[misc]
    for value in (
        generation.provider_model_name,
        str(generation.organization_public_id),
    ):
        assert value not in repr(generation)


@pytest.mark.parametrize(
    "attribute,value",
    [
        ("organization_public_id", UUID(int=0)),
        ("document_public_id", "invalid"),
        ("configured_model_public_id", None),
        ("embedding_generation", True),
        ("embedding_generation", 0),
        ("embedding_generation", 1.5),
        ("embedding_dimension", True),
        ("embedding_dimension", 0),
        ("embedding_dimension", 1.0),
        ("embedding_version", ""),
        ("embedding_version", " input-v1"),
        ("embedding_version", "x" * 129),
        ("provider_type", "x" * 33),
        ("provider_type", " "),
        ("provider_model_name", "x" * 257),
        ("provider_model_name", "name "),
        ("status", "pending"),
        ("created_at", None),
        ("created_at", NOW.replace(tzinfo=None)),
        ("created_at", "invalid"),
        ("started_at", START),
        ("finished_at", FINISH),
        ("failure_code", "FAILED"),
    ],
)
def test_invalid_snapshots_are_rejected(attribute, value):
    with pytest.raises((ValueError, TypeError)):
        replace(pending(), **{attribute: value})


def test_every_legal_transition_preserves_identity_and_model_snapshot():
    initial = pending()
    processing = initial.start(at=START)
    completed = processing.complete(at=FINISH)
    for before, after in (
        (initial, processing),
        (processing, completed),
        (initial, initial.fail(at=FINISH, code="PRECONDITION_FAILED")),
        (processing, processing.fail(at=FINISH, code="INDEXING_FAILED")),
    ):
        assert before.is_immediate_successor(after)
        assert after.identity == initial.identity
        assert after.model_snapshot == initial.model_snapshot
        assert after.created_at == NOW


@pytest.mark.parametrize(
    "before_state,after_state", list(product(IndexingStatus, repeat=2))
)
def test_transition_matrix(before_state, after_state):
    initial = pending()
    states = {
        IndexingStatus.PENDING: initial,
        IndexingStatus.PROCESSING: initial.start(at=START),
        IndexingStatus.COMPLETED: initial.start(at=START).complete(at=FINISH),
        IndexingStatus.FAILED: initial.start(at=START).fail(at=FINISH, code="FAILED"),
    }
    valid = (before_state, after_state) in {
        (IndexingStatus.PENDING, IndexingStatus.PROCESSING),
        (IndexingStatus.PROCESSING, IndexingStatus.COMPLETED),
        (IndexingStatus.PROCESSING, IndexingStatus.FAILED),
    }
    assert states[before_state].is_immediate_successor(states[after_state]) is valid
    # PENDING -> FAILED is legal only when no processing start is invented.
    assert initial.is_immediate_successor(initial.fail(at=FINISH, code="FAILED"))


@pytest.mark.parametrize(
    "attribute,value",
    [
        ("organization_public_id", uuid4()),
        ("document_public_id", uuid4()),
        ("configured_model_public_id", uuid4()),
        ("embedding_generation", 2),
        ("embedding_version", "v2"),
        ("provider_type", "another-provider"),
        ("provider_model_name", "another-model"),
        ("embedding_dimension", 1024),
        ("created_at", NOW - timedelta(seconds=1)),
    ],
)
def test_successor_cannot_change_identity_or_immutable_metadata(attribute, value):
    generation = pending()
    assert not generation.is_immediate_successor(
        replace(generation.start(at=START), **{attribute: value})
    )


@pytest.mark.parametrize(
    "code", [None, "", "provider secret payload", "bad-code", "x" * 65, "1INVALID"]
)
def test_failure_requires_a_bounded_safe_code(code):
    with pytest.raises((ValueError, TypeError)):
        pending().fail(at=FINISH, code=code)


def test_timestamps_and_lifecycle_metadata_are_consistent():
    generation = pending()
    with pytest.raises(ValueError):
        generation.start(at=NOW - timedelta(seconds=1))
    with pytest.raises(ValueError):
        generation.start(at=START).complete(at=NOW)
    with pytest.raises(ValueError):
        generation.fail(at=NOW - timedelta(seconds=1), code="FAILED")
    for value in (
        replace(
            generation,
            status=IndexingStatus.FAILED,
            finished_at=FINISH,
            failure_code="FAILED",
        ),
        generation.start(at=START).complete(at=FINISH),
    ):
        with pytest.raises(IndexingTransitionError):
            value.start(at=FINISH)
        with pytest.raises(IndexingTransitionError):
            value.complete(at=FINISH)
        with pytest.raises(IndexingTransitionError):
            value.fail(at=FINISH, code="FAILED")
    with pytest.raises(IndexingTransitionError):
        generation.complete(at=FINISH)
