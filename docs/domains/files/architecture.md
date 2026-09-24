# File Domain Architecture

**Status:** Implemented Phase 5 upload-intent validation and storage-key policy

## Purpose

The File capability owns metadata for a tenant-owned binary object. Phase 1
provides the domain and PostgreSQL persistence foundation. Phase 2 adds the
provider-neutral contract for binary object storage. Phase 3 provides the first
infrastructure adapter using the native asynchronous Azure Blob SDK. It does
not process Files or expose Files through an API. Phase 4 composes the adapter
as an application-owned dependency for local Azurite and Azure Managed Identity.
Phase 5 adds a pure application policy for validating untrusted upload metadata
and generating opaque Nexus storage keys. It performs no persistence, storage,
or network I/O.

## Boundary

```text
Future File upload application service
        ├── UploadIntentPolicy
        │       ↓
        │   ValidatedUploadIntent
        │
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
remain infrastructure details. `UploadIntentPolicy` is an application policy,
but it is provider-neutral and has no dependency on persistence or storage
ports.

## File semantics

A File represents:

- public File identity;
- organization and creator ownership;
- original user-visible name and MIME metadata;
- optional verified byte size of the stored object;
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

The size accepted by `UploadIntentPolicy` is deliberately named
`declared_size_bytes`: it is untrusted request metadata. It is not copied into
`File.size_bytes` while a File is pending. The intended later lifecycle is:

```text
ValidatedUploadIntent.declared_size_bytes
    untrusted client declaration

File(PENDING).size_bytes
    None

File(AVAILABLE).size_bytes
    actual verified object size
```

A later verification phase must measure the stored object before making the
File available.

## Tenant ownership

Every File belongs to exactly one Organization. The persistence schema enforces
that its creator User belongs to that same Organization. Reads require both the
authenticated organization public ID and File public ID so unknown and
cross-tenant resources have the same result.

Creator identity records provenance. It is not a substitute for application
authorization, which belongs to later File use cases.

## Storage identity

`storage_key` is an opaque logical identity, not a URL, filesystem path,
container name, bucket, credential, or access token. `UploadIntentPolicy`
generates the canonical form `files/<uuid4 hex>` only after input validation
succeeds. `ObjectStorage` and its infrastructure adapters receive the
resulting key and treat it as opaque.

The original filename is display metadata and must not become physical object
identity. Storage keys contain no filename, extension, MIME type, organization,
user, project, workspace, provider, account, container, bucket, URL, or
credential. Authorization comes from persisted File metadata and application
policy, never from possession or interpretation of a storage key.

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
creates the container and never closes the shared client. Application
composition owns client construction, credentials, container selection, and
application-lifetime cleanup.

Object creation streams the caller's asynchronous byte iterable into the SDK
as an explicit Block Blob with `overwrite=False`. A private pass-through
records producer-origin failures without buffering content, so caller failures
remain distinct from Azure destination failures. This preserves single-pass
uploads and uses Azure's atomic create-only behavior without an existence
preflight. Existing blobs map to the provider-neutral
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
also available in the local development Docker Compose stack.

## Storage configuration and composition

`StorageComposition` selects the configured provider with one explicit branch,
constructs its resources, exposes only `ObjectStorage`, and owns asynchronous
cleanup. The root `AppContainer` owns this composition for the FastAPI
application lifetime. Azure SDK clients and credentials remain inside
infrastructure and composition.

Connection-string authentication is restricted to the explicit `development`
and `test` environments and is intended only for Azurite. Every other
environment, including unknown values, requires an HTTPS Azure Storage account
URL and `ManagedIdentityCredential`. A configured client ID selects a
user-assigned identity; otherwise Nexus uses the system-assigned identity.
Nexus supports no production account-key, client-secret, interactive, or SAS
authentication in this phase.

The relevant runtime settings are:

- `STORAGE_PROVIDER=azure_blob`;
- `AZURE_STORAGE_CONTAINER` for the externally provisioned container;
- `AZURE_STORAGE_CONNECTION_STRING` only for `development` and `test`;
- `AZURE_STORAGE_ACCOUNT_URL` for Managed Identity environments;
- optional `AZURE_STORAGE_MANAGED_IDENTITY_CLIENT_ID` for a user-assigned
  identity.

Connection string and account URL authentication are mutually exclusive.

Composition creates a top-level asynchronous `BlobServiceClient` and derives
the configured `ContainerClient`, which `AzureBlobObjectStorage` borrows. The
top-level client and any Managed Identity credential are closed during
application shutdown. Client construction does not create or probe the
container. Deployment infrastructure must provision the configured container
before File operations use it.

The production Managed Identity needs Blob data-plane permission for current
create, read, and delete operations. `Storage Blob Data Contributor` is the
normal built-in role; assign it at the configured container scope where
practical. Nexus does not provision RBAC at runtime.

Future User Delegation SAS work is separate. It will additionally require the
`Microsoft.Storage/storageAccounts/blobServices/generateUserDelegationKey/action`
permission at storage-account scope or higher, for example through the
`Storage Blob Delegator` role. Phase 4 neither grants that permission nor
implements upload grants.

## Upload-intent policy

`UploadIntentPolicy` is the Phase 5 pure application boundary for preparing an
upload request. It accepts an original filename, optional declared MIME type,
and declared size, then returns an immutable `ValidatedUploadIntent` containing
normalized metadata, `declared_size_bytes`, and a newly generated opaque
storage key. It does not authorize a user, create a File, query PostgreSQL,
contact object storage, or issue an upload grant.

Filename handling is intentionally metadata-focused rather than filesystem or
cloud-path policy:

- surrounding whitespace is removed;
- blank names, `/`, `\`, and Unicode `Cc` control characters are rejected;
- names are bounded by the File domain's 255-character limit;
- Unicode, internal spaces, ordinary extensions, multiple dots, and leading
  dots remain valid.

The policy does not apply basename extraction, Unicode rewriting, platform
reserved-name rules, or provider-specific sanitization. A filename remains
untrusted display metadata in later UI and download-response handling.

MIME metadata is also a declaration rather than verified content identity.
Absent or blank input becomes `application/octet-stream`; other values are
trimmed, lowercased, bounded by the File domain's 255-character limit, and must
be a single bare `type/subtype`. Vendor types and structured suffixes remain
valid. Parameters, wildcards, embedded whitespace, control characters, and
malformed values are rejected. Phase 5 has no MIME allowlist and does not
compare the MIME value with a filename extension.

Declared size must be an integer other than `bool`, must be nonnegative, and
must not exceed `FILE_UPLOAD_MAX_SIZE_BYTES`. The initial configurable default
is 52,428,800 bytes (50 MiB), and zero-byte uploads are valid. This limit does
not prove the object's actual size and is not an object-storage capability
limit.

The generated `files/<uuid4 hex>` key is 38 provider-portable ASCII characters
using lowercase hexadecimal plus `/`. Nexus performs no database or storage
existence preflight and no deduplication. The database uniqueness constraint
and create-only object storage semantics remain the final collision defenses.

Validation failures use one application error contract with fixed,
non-sensitive messages. Invalid filenames, MIME values, and sizes are never
echoed into an error. Transport-specific error mapping belongs to the later
File API phase.

## Future upload and verification lifecycle

Phase 5 prepares but does not execute a direct upload. Later phases can compose
the policy without changing its boundary:

```text
authenticate and authorize upload
        ↓
UploadIntentPolicy
        ↓
persist File(PENDING) with size_bytes=None
        ↓
issue an exact-object upload grant
        ↓
client uploads directly to object storage
        ↓
verify actual object size, type, checksum, and security state
        ↓
transition File to AVAILABLE or FAILED
```

The client never chooses the storage key. A successful object upload or a
provider event alone does not establish tenant ownership, authorization, or
File availability. Later verification must compare the actual object size
with both `declared_size_bytes` and the configured maximum, inspect actual
content type where required, compute integrity metadata, and apply future
malware/security policy before persisting the verified final size.

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

The upload intent likewise contains no Document, chunk, embedding, vector,
retrieval, MCP-resource, tool, or Agent metadata. Future Document processing
starts only from an authorized, verified File. Future MCP and Agent operations
must resolve that File through Nexus authorization boundaries; neither an
opaque storage key nor an upload intent grants access.

The canonical storage key is portable across Azure Blob, S3, and future object
stores. Changing the configured adapter must not require changing File identity
or adding provider concepts to upload validation.

## Phase boundaries

```text
Phase 2
    ObjectStorage contract only

Phase 3
    Azure Blob adapter, Azure SDK integration, and Azurite tests (implemented)

Phase 4
    storage configuration, provider selection, and composition (implemented)

Phase 5
    upload-intent validation and storage-key generation (implemented)
```

## Deferred work

Later phases own:

- authorization, File(PENDING) creation, and upload application orchestration;
- upload grants and provider-specific direct-upload credentials;
- actual size, type, checksum, and security verification;
- File lifecycle transitions after storage verification;
- upload and management APIs;
- list, download, and delete use cases and APIs;
- retention and object cleanup;
- Document processing, chunks, embeddings, and RAG;
- frontend File workflows.
