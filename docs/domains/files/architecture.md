# File Domain Architecture

**Status:** Implemented Phase 3 Azure Blob storage adapter

## Purpose

The File capability owns metadata for a tenant-owned binary object. Phase 1
provides the domain and PostgreSQL persistence foundation. Phase 2 adds the
provider-neutral contract for binary object storage. Phase 3 provides the first
infrastructure adapter using the native asynchronous Azure Blob SDK. It does
not yet configure the provider, process Files, or expose Files through an API.

## Boundary

```text
Future File application service
        ├── FilePersistence
        │       ↓
        │   SqlAlchemyFilePersistence
        │       ↓
        │   AsyncSession / PostgreSQL
        │
        └── ObjectStorage
                ↑
        AzureBlobObjectStorage
                ↓
        Async Azure ContainerClient
```

The File domain and ports do not depend on FastAPI, SQLAlchemy, or a cloud
provider. SQLAlchemy remains inside infrastructure. Binary storage adapters
will also remain infrastructure details.

## File semantics

A File represents:

- public File identity;
- organization and creator ownership;
- original user-visible name and MIME metadata;
- optional final byte size while storage is pending;
- an opaque provider-neutral storage key;
- storage lifecycle state;
- optional SHA-256 integrity metadata;
- creation and update timestamps.

The storage states are:

```text
pending
available
failed
```

An available File must have a known size. A SHA-256 checksum remains optional
in every state and is validated only when present. Phase 1 does not implement
checksum-based deduplication.

## Tenant ownership

Every File belongs to exactly one Organization. The persistence schema enforces
that its creator User belongs to that same Organization. Reads require both the
authenticated organization public ID and File public ID so unknown and
cross-tenant resources have the same result.

Creator identity records provenance. It is not a substitute for application
authorization, which belongs to later File use cases.

## Storage identity

`storage_key` is an opaque logical identity, not a URL, filesystem path,
container name, bucket, credential, or access token. Its detailed generation
and validation rules belong to the future upload application boundary and
storage adapter.

The original filename is display metadata and must not become physical object
identity.

Nexus currently assumes one configured object-storage backend and therefore
does not persist a provider or container per File. A future multi-backend
requirement must be reviewed before adding a storage-location abstraction.

## Object storage contract

`ObjectStorage` is the provider-neutral boundary for File binary content. It
supports three operations:

- streamed, single-pass object creation;
- lazy streamed reads;
- idempotent deletion.

Creation is create-only: a future adapter must enforce the new-object condition
atomically and translate an existing key into
`ObjectStorageAlreadyExistsError`. The port does not require buffering the
entire upload.

`stream_object()` returns an `AsyncIterator[bytes]` directly. Provider I/O is
lazy, so the method does not promise an eager existence check. A missing object
may raise `ObjectStorageNotFoundError` when iteration begins, and another
provider failure may raise `ObjectStorageError` after streaming has started.
Callers must therefore handle storage errors while consuming the iterator.
There is no separate existence or metadata preflight operation.

Deletion is idempotent: deleting an already-absent object succeeds. Provider
SDK exceptions must be translated to the provider-neutral errors at the future
adapter boundary. Cancellation remains cancellation; retry policy belongs to
the calling use case or infrastructure policy, not this port.

A concrete adapter is responsible for releasing its provider resources when a
stream completes, fails, is cancelled, or its underlying async generator is
closed. The port uses the standard asynchronous iterator contract and does not
introduce a custom closable stream.

PostgreSQL stores File ownership and metadata. Object storage holds binary
content addressed by the opaque `storage_key`; neither side exposes
provider-specific location details through the File boundary.

## Azure Blob infrastructure adapter

`AzureBlobObjectStorage` lives under `nexus.infrastructure.storage` and is the
only File storage implementation that imports the Azure SDK. It receives a
preconfigured asynchronous `ContainerClient` and borrows it: the adapter never
creates the container and never closes the shared client. Future Phase 4
composition owns client construction, credentials, container selection, and
application-lifetime cleanup.

Object creation passes the caller's asynchronous byte iterable directly to the
SDK as an explicit Block Blob with `overwrite=False`. This preserves streamed,
single-pass uploads and uses Azure's atomic create-only behavior without an
existence preflight. Existing blobs map to the provider-neutral
`ObjectStorageAlreadyExistsError`.

Downloads remain lazy. `stream_object()` returns an asynchronous generator and
does not call Azure until iteration begins. It yields chunks from the Azure
downloader without reading the complete blob into memory. Missing blobs and
other provider failures may therefore surface while the returned iterator is
being consumed and are translated to provider-neutral storage errors.

The Azure downloader has no public per-download close operation. The adapter
does not access private downloader or HTTP state and does not close the shared
client. Instead, each in-flight Azure download operation is retained and
allowed to settle before outer task cancellation is propagated. At a yielded
chunk boundary no provider operation is in flight, so closing the Nexus async
generator early does not drain the remaining blob or invalidate the shared
client. Normal completion, failure, cancellation, and early generator closure
are covered by adapter tests, including shared-client reuse.

Deletion is idempotent: Azure not-found results are accepted only for delete.
Other Azure failures use safe provider-neutral messages. The adapter adds no
application retry loop and uses the retry/pipeline behavior already configured
on the injected client.

Azurite integration tests verify streamed round trips, create conflicts,
missing reads, idempotent deletion, empty objects, and client reuse. Azurite is
test infrastructure only and is not part of the Nexus application composition.

## File and Document separation

```text
File
    binary object, ownership, and storage metadata

Document (future)
    parsed and indexable representation derived from a File
```

File does not own extracted text, pages, chunks, embeddings, retrieval state,
vector identifiers, or Document processing status.

## Future RAG, MCP, and Agent compatibility

Future File application services, Document processors, parsers, RAG ingestion
pipelines, MCP-facing use cases, and Agents can consume File content through
the File capability and `ObjectStorage` without depending directly on Azure,
S3, or another provider:

```text
Application / Document Processing / RAG / MCP-facing use cases / Agents
                                ↓
                         File capability
                                ↓
                         ObjectStorage
                                ↑
                       infrastructure adapter
```

Binary storage remains separate from extraction, chunks, embeddings, vector
storage, retrieval, and processing state. Stable File identity and an opaque
storage key are sufficient for a later Document-to-File relationship.

Future MCP tools and resources must access Files through Nexus application and
authorization boundaries rather than provider infrastructure. Organization,
workspace/project, retrieval, tool-permission, and audit enforcement belong to
those later application and security phases. The storage port contains no RAG,
MCP, Agent, authorization, or provider-credential concepts.

## Phase boundaries

```text
Phase 2
    ObjectStorage contract only

Phase 3
    Azure Blob adapter, Azure SDK integration, and Azurite tests (implemented)

Phase 4
    storage configuration, provider selection, and composition
```

## Deferred work

Later phases own:

- storage configuration and composition;
- upload application service and API;
- key generation and filename/upload validation;
- list, download, and delete use cases and APIs;
- retention and object cleanup;
- Document processing, chunks, embeddings, and RAG;
- frontend File workflows.
