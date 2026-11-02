# Retrieval contracts (RF-01)

The implemented boundary is:

```text
Document Processing -> Retrieval domain contracts -> future retrieval implementations
```

Document Processing owns authoritative, immutable chunk sets and their source
provenance. Retrieval consumes those domain values; it does not modify their
persistence or lifecycle. See [Document Processing](../files/architecture.md).

## Contracts

`nexus.retrieval.domain` exports four frozen dataclasses:

- `RetrievalScope` requires a nonzero organization public UUID.
- `RetrievalRequest` requires that scope, original meaningful query text of at
  most 8,192 Unicode characters, and an explicit exact-integer `top_k` from 1 to
  100. Validation preserves the query, including surrounding whitespace. Top-K
  limits final results, not a future internal candidate budget.
- `RetrievedChunk` wraps the existing `DocumentChunkCandidate`, retaining its
  original index, text, kind, section path and ordered `SourceContribution`
  values. It also carries organization/Document/source File public UUIDs,
  verified source ETag, processing recipe version, extractor/normalizer/segmenter
  identities and versions, and optional total page count. Segmentation settings
  and their bounds validation stay on the authoritative Document Processing chunk
  set; retrieval does not repeat them on each selected chunk.
- `RetrievalResult` retains its request and an immutable tuple in final ranking
  order. Empty and partial results are valid. More than `top_k` results,
  mismatched tenants, and duplicate chunk identities are rejected, never silently
  truncated, deduplicated or reordered.

Logical chunk identity is `(document_public_id, chunk.index)`. The Document UUID
already identifies one immutable processing generation. Explicit reprocessing
creates a new Document UUID and preserves prior generations. Numeric database
chunk IDs remain internal; retrieval introduces no additional chunk UUID.
The Document reference retains generation identity even when reprocessing changes
segmentation settings; component and recipe versions remain available in results.

Contributions remain structured: original block indexes and kinds, one-based
end-exclusive line ranges or page numbers, list metadata, quote depth and optional
zero-based end-exclusive normalized-text slices. Section paths reference source
heading indexes. Noncontiguous pages remain noncontiguous; no synthetic page/line
range or flattened provenance replaces them. The candidate owns these invariants.

## Authorization boundary

Constructing a scope validates tenant identity and grants no permission. A future
application service must derive organization identity from authenticated trusted
context, retain the principal, and enforce applicable document/resource access
before returning content. A client organization UUID or organization-wide
permission alone must not establish document access. Tenant-filtered persistence
and result tenant checks are defense in depth, not resource authorization.

Content-bearing dataclasses omit their fields from `repr`; callers must still
avoid logging queries, chunks, source metadata, or provenance explicitly. Domain
validation errors do not include supplied values. Constructors accept domain
objects, never ORM rows, transport schemas, or provider SDK objects.
The dependency-boundary test applies only to `nexus.retrieval.domain`; future
retrieval application services may use authorized model-provider and infrastructure
dependencies within their application boundaries.

## Later phases

Requests contain no provider, embedding model, dimension, vector or algorithm.
Embedding/index generations will be separate versioned retrieval data associated
with stable chunk references, without changing authoritative DocumentChunks.
Dense and PostgreSQL lexical retrieval can share these requests and results;
hybrid retrieval, evaluation and RRF can use stable identities and ordered lists.
Reranking can reorder chunks without losing source/citation facts.

There is no universal score: dense distances, lexical scores, fusion scores and
reranker scores need strategy-specific semantics in their owning later phases.
RF-01 implements no search, embeddings, indexing, metadata lookup, API, worker,
Knowledge Base or Project model, or retrieval authorization policy.
