"""Immutable embedding values, independent of providers and model resolution."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

MAX_EMBEDDING_BATCH_SIZE = 128
MAX_EMBEDDING_INPUT_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True, repr=False)
class EmbeddingRequest:
    """An ordered bounded batch; validation preserves original input text."""

    texts: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.texts, tuple) or not (
            1 <= len(self.texts) <= MAX_EMBEDDING_BATCH_SIZE
        ):
            raise ValueError("Embedding request requires 1 to 128 immutable texts")
        total_bytes = 0
        for text in self.texts:
            if not isinstance(text, str):
                raise TypeError("Embedding inputs must be text")
            # Bound allocation before encoding; UTF-8 needs at least one byte per character.
            if len(text) > MAX_EMBEDDING_INPUT_BYTES - total_bytes:
                raise ValueError("Embedding input exceeds the aggregate UTF-8 limit")
            try:
                total_bytes += len(text.encode("utf-8"))
            except UnicodeEncodeError:
                raise ValueError("Embedding inputs must be valid UTF-8 text") from None
            if total_bytes > MAX_EMBEDDING_INPUT_BYTES:
                raise ValueError("Embedding input exceeds the aggregate UTF-8 limit")
            if not text.strip():
                raise ValueError("Embedding inputs must contain meaningful text")


@dataclass(frozen=True, slots=True, repr=False)
class EmbeddingResult:
    """Vectors in request order; adapters validate count and dimension before return."""

    vectors: tuple[tuple[float, ...], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.vectors, tuple) or not (
            1 <= len(self.vectors) <= MAX_EMBEDDING_BATCH_SIZE
        ):
            raise ValueError("Embedding result requires 1 to 128 immutable vectors")
        if any(not isinstance(vector, tuple) or not vector for vector in self.vectors):
            raise ValueError("Embedding vectors must be nonempty immutable tuples")
        if any(len(vector) != self.dimension for vector in self.vectors):
            raise ValueError("Embedding vector dimensions must be consistent")
        if any(
            type(value) is not float or not isfinite(value)
            for vector in self.vectors
            for value in vector
        ):
            raise ValueError("Embedding vector values must be finite floats")

    @property
    def dimension(self) -> int:
        return len(self.vectors[0])

    def validate_for(
        self, *, request: EmbeddingRequest, expected_dimension: int
    ) -> None:
        """Check invocation-specific invariants without retaining text or credentials."""
        if not isinstance(request, EmbeddingRequest):
            raise TypeError("Embedding result validation requires an embedding request")
        if type(expected_dimension) is not int or expected_dimension <= 0:
            raise ValueError("Expected embedding dimension must be a positive integer")
        if len(self.vectors) != len(request.texts):
            raise ValueError("Embedding output count does not match the request")
        if self.dimension != expected_dimension:
            raise ValueError("Embedding output dimension does not match the model")
