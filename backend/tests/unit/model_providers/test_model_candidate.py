import pytest

from nexus.model_providers.domain import (
    ModelCandidate,
    ModelCapability,
    ModelProviderConfigurationError,
    ModelType,
)


def test_embedding_candidate_may_have_unknown_dimension() -> None:
    candidate = ModelCandidate(
        provider_model_name="text-embedding-model",
        display_name="Embedding model",
        model_type=ModelType.EMBEDDING,
    )

    assert candidate.embedding_dimension is None


def test_non_chat_candidate_rejects_chat_capabilities() -> None:
    with pytest.raises(ModelProviderConfigurationError):
        ModelCandidate(
            provider_model_name="embedding-model",
            display_name="Embedding model",
            model_type=ModelType.EMBEDDING,
            capabilities=frozenset({ModelCapability.STREAMING}),
        )


def test_known_embedding_dimension_must_be_positive() -> None:
    with pytest.raises(ModelProviderConfigurationError):
        ModelCandidate(
            provider_model_name="embedding-model",
            display_name="Embedding model",
            model_type=ModelType.EMBEDDING,
            embedding_dimension=0,
        )
