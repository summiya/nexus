"""Immutable retrieval requests and provenance-preserving results."""

from nexus.retrieval.domain.contracts import (
    MAX_QUERY_LENGTH,
    MAX_TOP_K,
    RetrievalRequest,
    RetrievalResult,
    RetrievalScope,
    RetrievedChunk,
)

__all__ = [
    "MAX_QUERY_LENGTH",
    "MAX_TOP_K",
    "RetrievalRequest",
    "RetrievalResult",
    "RetrievalScope",
    "RetrievedChunk",
]
