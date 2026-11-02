from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError, replace
from typing import get_type_hints

import pytest

from nexus.llm.domain import (
    MAX_EMBEDDING_BATCH_SIZE,
    MAX_EMBEDDING_INPUT_BYTES,
    EmbeddingRequest,
    EmbeddingResult,
)
from nexus.model_providers.domain import ResolvedEmbeddingModel
from nexus.model_providers.ports import EmbeddingGateway


@pytest.mark.parametrize("texts", [("first",), ("first", "second"), ("x",) * 128])
def test_embedding_request_accepts_bounded_ordered_immutable_inputs(texts):
    request = EmbeddingRequest(texts)
    assert request.texts is texts
    assert MAX_EMBEDDING_BATCH_SIZE == 128


@pytest.mark.parametrize("texts", [None, [], ["text"], "text", (), ("x",) * 129])
def test_embedding_request_rejects_invalid_batch_shape_or_count(texts):
    with pytest.raises(ValueError):
        EmbeddingRequest(texts)


@pytest.mark.parametrize("text", [None, 1, True, b"bytes"])
def test_embedding_request_rejects_non_text_inputs(text):
    with pytest.raises(TypeError):
        EmbeddingRequest((text,))


@pytest.mark.parametrize("text", ["", " \t\n", "\u2003\u00a0"])
def test_embedding_request_requires_meaningful_content_for_every_input(text):
    with pytest.raises(ValueError):
        EmbeddingRequest(("valid", text))


def test_embedding_request_preserves_unicode_whitespace_duplicates_and_order():
    texts = (" \t日本語 Café: A+B?\n", "same", "same")
    assert EmbeddingRequest(texts).texts == texts


def test_embedding_input_limit_is_aggregate_utf8_bytes_not_characters():
    assert MAX_EMBEDDING_INPUT_BYTES == 1024 * 1024
    limit = MAX_EMBEDDING_INPUT_BYTES
    EmbeddingRequest(("x" * limit,))
    EmbeddingRequest(("é" * (limit // 2),))
    EmbeddingRequest(("a", "x" * (limit - 1)))
    for texts in (
        ("x" * (limit + 1),),
        ("é" * (limit // 2 + 1),),
        ("a", "x" * limit),
        ("a", "é" * (limit // 2)),
    ):
        with pytest.raises(ValueError, match="aggregate UTF-8 limit"):
            EmbeddingRequest(texts)


def test_invalid_unicode_is_rejected_without_input_in_error_or_exception_context():
    private_text = "private embedding input \ud800"
    with pytest.raises(ValueError) as raised:
        EmbeddingRequest((private_text,))
    assert "private embedding input" not in str(raised.value)
    assert raised.value.__suppress_context__ is True


@pytest.mark.parametrize("count", [1, 128])
def test_embedding_result_preserves_order_and_derives_dimension(count):
    vectors = tuple((float(i), -0.5) for i in range(count))
    result = EmbeddingResult(vectors)
    assert result.vectors is vectors
    assert result.dimension == 2
    result.validate_for(
        request=EmbeddingRequest(("text",) * count), expected_dimension=2
    )


@pytest.mark.parametrize("vectors", [None, [], [[0.1]], (), ((0.1,),) * 129])
def test_embedding_result_rejects_invalid_batch_shape_or_count(vectors):
    with pytest.raises(ValueError):
        EmbeddingResult(vectors)


@pytest.mark.parametrize("vector", [None, [], [0.1], (), "vector", 0.1])
def test_embedding_result_requires_nonempty_immutable_vectors(vector):
    with pytest.raises(ValueError):
        EmbeddingResult((vector,))


def test_embedding_result_rejects_inconsistent_vector_widths():
    with pytest.raises(ValueError, match="dimensions must be consistent"):
        EmbeddingResult(((0.1,), (0.2, 0.3)))


@pytest.mark.parametrize(
    "value", [True, False, 1, "0.1", None, float("nan"), float("inf"), -float("inf")]
)
def test_embedding_result_rejects_non_float_or_nonfinite_values_in_any_vector(value):
    with pytest.raises(ValueError, match="finite floats"):
        EmbeddingResult(((0.1, 0.2), (0.3, value)))


@pytest.mark.parametrize("vectors", [((0.1,),), ((0.1,), (0.2,), (0.3,))])
def test_embedding_result_rejects_missing_and_excess_outputs(vectors):
    result = EmbeddingResult(vectors)
    with pytest.raises(ValueError, match="output count"):
        result.validate_for(
            request=EmbeddingRequest(("first", "second")), expected_dimension=1
        )


def test_embedding_result_rejects_wrong_configured_dimension():
    result = EmbeddingResult(((0.1, 0.2),))
    with pytest.raises(ValueError, match="output dimension"):
        result.validate_for(request=EmbeddingRequest(("text",)), expected_dimension=3)


@pytest.mark.parametrize("dimension", [None, True, False, 1.0, "1", 0, -1])
def test_embedding_result_validation_requires_an_exact_positive_dimension(dimension):
    with pytest.raises(ValueError, match="positive integer"):
        EmbeddingResult(((0.1,),)).validate_for(
            request=EmbeddingRequest(("text",)), expected_dimension=dimension
        )


@pytest.mark.parametrize("invalid_request", [None, {}, ("text",)])
def test_embedding_result_validation_requires_its_semantic_request(invalid_request):
    with pytest.raises(TypeError):
        EmbeddingResult(((0.1,),)).validate_for(
            request=invalid_request, expected_dimension=1
        )


def test_embedding_values_are_immutable_and_exclude_payloads_from_representations():
    request = EmbeddingRequest(("private text must stay hidden",))
    result = EmbeddingResult(((8675309.125,),))
    for value, field, payload in (
        (request, "texts", request.texts[0]),
        (result, "vectors", "8675309.125"),
    ):
        assert payload not in repr(value)
        assert payload not in str(value)
        with pytest.raises(FrozenInstanceError):
            setattr(value, field, ())
    assert replace(result).vectors is result.vectors


def test_embedding_gateway_is_an_async_typed_keyword_only_runtime_boundary():
    method = EmbeddingGateway.embed
    signature = inspect.signature(method)
    assert inspect.iscoroutinefunction(method)
    assert list(signature.parameters) == ["self", "request", "target"]
    assert signature.parameters["request"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["target"].kind is inspect.Parameter.KEYWORD_ONLY
    assert get_type_hints(method) == {
        "request": EmbeddingRequest,
        "target": ResolvedEmbeddingModel,
        "return": EmbeddingResult,
    }
