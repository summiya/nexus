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

## RF-06: durable indexing lifecycle

RF-06 extends the lifecycle-contract scope with one durable generation table and
short transactional persistence operations. This approved persistence extension
does not coordinate embedding execution or introduce an indexing pipeline.

`IndexingGeneration` is a frozen, model-neutral value identified by organization,
Document and configured-model public UUIDs plus a positive embedding generation.
It freezes provider type, invocation name, dimension and embedding/input-format
version without credentials, content, vectors or duplicated source provenance.
The domain accepts any bounded model identity and positive dimension. The current
persistence adapter admits only RF-05's OpenAI/small/1536 storage profile, matching
an enabled tenant-owned configured model/provider under lock. It does not resolve
credentials or call a provider. A future executor must match its resolved target
to this frozen snapshot; an FK or declared snapshot is not provider attestation.

Legal transitions are PENDING -> PROCESSING -> COMPLETED or FAILED, with
PENDING -> FAILED also allowed for terminal precondition failure. Terminal states
cannot reopen; replacement work reserves a new generation. Failures record only
a bounded safe code, never exception messages or provider payloads. All timestamps
are aware and chronological. Document processing retains its existing states;
no EMBEDDING or INDEXED Document state exists.

Every mutation locks the tenant-owned Document first, then the generation, then
model/provider rows when eligibility must be checked. The source must be a
COMPLETED Document with a complete immutable authoritative chunk set. New
generation numbers must equal one plus the maximum across lifecycle headers and
existing vector generations for that document/model. Only one tracked generation
may be PENDING/PROCESSING for the pair. Exact creation replays return the current
snapshot; expected-snapshot updates accept one legal successor, acknowledge exact
transition replays and reject stale or divergent proposals. Frozen metadata is
never rewritten. These are short transactions, not locks held over provider I/O.

RF-05 compatibility uses the same Document lock:

- Before a document/model has tracking, existing RF-05 write behaviour is retained.
- Existing untracked generations remain legacy and may receive further valid
  batches, even after tracking begins. No migration adopts or marks them complete.
- After tracking begins, a new untracked generation is rejected. Callers must
  reserve its next number through lifecycle persistence; legacy numbers cannot
  collide with or be adopted as tracked generations.
- Tracked batches must match the immutable header. New vectors require PROCESSING.
  Exact durable duplicates retain RF-05's float32 comparison and current-model
  eligibility semantics; a disabled model still permits an otherwise valid exact
  duplicate. A changed invocation configuration can still cause an RF-05 conflict.

Before COMPLETED, one transaction checks authoritative chunk count/contiguous
indexes, both directions of chunk-ID set equality against stored embeddings, and
the snapshot metadata of every vector for that document/model/generation. Merely
having vectors, matching counts, or completing a single batch is insufficient.
The shared Document lock serializes this check with concurrent RF-05 writes.

Task cancellation waits for transaction commit/rollback, then propagates
`CancelledError`. It does not imply durable cancellation or failure: callers must
reread state and may replay the identical operation. FAILED preserves partial
vectors. Abandoned PROCESSING recovery, leases, explicit cancellation commands,
workers, retry policy, provider execution and RF-07 orchestration are excluded.

Persistence requires trusted authorized tenant context; missing and foreign
references are indistinguishable. No API or automatic activation is added. Future
retrieval must require a compatible tracked COMPLETED generation and current
resource authorization before Top-K; lifecycle completion is not an access grant.
