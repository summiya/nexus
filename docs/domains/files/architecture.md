# File Domain Architecture

**Status:** Implemented Phase 8 authorized upload initiation and trusted upload state

## Purpose

The File capability owns metadata for a tenant-owned binary object. Phase 1
provides the domain and PostgreSQL persistence foundation. Phase 2 adds the
provider-neutral contract for binary object storage. Phase 3 provides the first
infrastructure adapter using the native asynchronous Azure Blob SDK. It does
not process Files or expose Files through an API. Phase 4 composes the adapter
as an application-owned dependency for local Azurite and Azure Managed Identity.
Phase 5 adds a pure application policy for validating untrusted upload metadata
and generating opaque Nexus storage keys. It performs no persistence, storage,
or network I/O. Phase 6 adds the provider-neutral boundary for issuing a
short-lived, exact-object browser upload capability. It does not implement a
provider signer or compose that capability into the application. Phase 7 adds
the Azure User Delegation SAS implementation of that boundary without changing
application composition or exposing Azure types outside infrastructure. Phase 8
adds runtime RBAC enforcement, application orchestration, and atomic persistence
of a pending File plus its trusted upload-attempt metadata. It still exposes no
HTTP API.

## Boundary

```text
InitiateFileUpload
        ├── PermissionChecker
        │       ↑
        │   SqlAlchemyPermissionChecker
        │
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
        └── UploadGrantIssuer
                ↑
        AzureUserDelegationUploadGrantIssuer
                ↓
        Borrowed async BlobServiceClient

File binary storage operations
        ↓
ObjectStorage
        ↑
AzureBlobObjectStorage
        ↓
Async Azure ContainerClient
```

The File domain and ports do not depend on FastAPI, SQLAlchemy, or a cloud
provider. SQLAlchemy remains inside infrastructure. Binary storage adapters
remain infrastructure details. `UploadIntentPolicy` is an application policy,
but it is provider-neutral and has no dependency on persistence or storage
ports. `UploadGrantIssuer` is a separate application-facing capability from
`ObjectStorage`; Phase 6 adds only its provider-neutral contract.
`AzureUserDelegationUploadGrantIssuer` implements that contract inside
infrastructure and borrows the application-owned Azure service client.

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

During Phase 5, `ValidatedUploadIntent.declared_size_bytes` exists only in
request/application memory. Phase 8 copies the accepted declaration into a
separate trusted `FileUploadAttempt`; `File(PENDING).size_bytes` remains `None`.
Do not overload `File.size_bytes` with untrusted request metadata. Later
asynchronous verification can compare the actual Blob size with the accepted
declaration without treating the declaration as verified storage truth.

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

## Upload grant contract

`UploadGrantIssuer` is the provider-neutral boundary for delegating one direct
browser upload. It is intentionally separate from `ObjectStorage`:

- `ObjectStorage` performs trusted backend binary operations;
- `UploadGrantIssuer` issues an ephemeral capability to an already-authorized
  caller.

The issuer receives only an already-generated opaque `storage_key` and an
application-selected, timezone-aware expiration timestamp. Authorization and
tenant, user, workspace, or project decisions must occur before it is called.
The issuer does not receive a filename, MIME type, declared size, container,
bucket, provider, credential, or client-selected object key.

`UploadGrant` returns the complete instructions a browser will eventually
execute:

- an opaque upload URL, which may contain provider signing query parameters;
- the HTTP method;
- an immutable mapping of required request headers;
- the actual timezone-aware expiration timestamp.

The application supplies the maximum requested expiration to the issuer. A
provider adapter may shorten that lifetime for provider clock-skew or signing
constraints, but the effective `UploadGrant.expires_at` must never be later
than the application-requested expiration.

The URL, method, and required headers are provider-issued instructions. Nexus
application code must preserve the signed URL and header names and values
without parsing provider credentials out of them or reconstructing
provider-specific behavior in the frontend. The neutral contract does not
require HTTPS because a local emulator may legitimately use HTTP; deployment
and provider configuration remain responsible for secure production transport.

Every issuer implementation must preserve the same security semantics:

```text
one exact canonical storage key
        +
create-only upload capability
        +
short expiration
```

A grant must not confer read, list, delete, container, bucket, prefix-wide, or
intentional overwrite access. Provider-specific adapters are responsible for
enforcing those semantics atomically. The contract does not promise a signed
URL is cryptographically single-use and does not introduce a token registry;
short lifetime, exact-object scope, and create-only behavior are the controls.

The grant URL and any sensitive required headers are temporary bearer
capabilities. They must not be logged, sent to telemetry, persisted in File
metadata, or exposed beyond the authorized caller. The provider-neutral port
does not depend on Pydantic or wrap these values in provider/configuration
types. Provider failures are translated into the single safe
`UploadGrantError`; cancellation remains cancellation.

The grant contains the instructions a future browser client needs, but Phase 6
does not configure Azure Storage, FastAPI, or frontend CORS. A deployment that
enables direct upload must separately allow its authorized frontend origin,
the issued method, and the required provider headers.

A future S3 or other provider adapter must return the same four grant fields
and preserve the same exact-object, create-only semantics. Provider signing
data and any provider-specific conditional headers remain inside that adapter;
no bucket, region, signature, or provider name enters the File application
contract.

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

Azure User Delegation SAS issuance additionally requires the
`Microsoft.Storage/storageAccounts/blobServices/generateUserDelegationKey/action`
permission at storage-account scope or higher, for example through the
`Storage Blob Delegator` role. Phase 4 neither grants that permission nor
provisions any role. The Phase 7 adapter assumes deployment has assigned it.

## Azure User Delegation upload-grant adapter

`AzureUserDelegationUploadGrantIssuer` implements `UploadGrantIssuer` with
Azure User Delegation SAS. It borrows the application-owned
`BlobServiceClient` and neither constructs nor closes a second service client
or credential. The adapter is responsible for:

- acquiring a User Delegation Key through the service client;
- generating a SAS scoped to the one exact Blob identified by `storage_key`;
- granting only the permission needed for create-only behavior;
- returning the complete signed Blob URL and required
  `x-ms-blob-type: BlockBlob` header;
- provider clock-skew handling and Azure exception translation.

The configured account and container are explicit inputs. The opaque
`storage_key` is passed unchanged to `BlobServiceClient.get_blob_client()`, and
the adapter uses the returned `BlobClient.url` rather than constructing a Blob
URL manually. Concrete issuer wiring remains a later composition concern; it
can be built beside `AzureBlobObjectStorage` from the same composition-owned
resources. Resource shutdown remains owned by `StorageComposition`. The
adapter owns no provider resource.

The issuer requests a delegation key whose start time includes a small
backward clock-skew allowance and whose preferred lifetime is approximately
one hour. It keeps one process-local cached key behind an `asyncio.Lock`, using
double-checked refresh so concurrent requests do not request duplicate keys.
A cached key is preferred for reuse only when it covers the requested grant
expiration plus the approximately five-minute refresh margin.

The cache margin is an optimization, not a provider validity requirement. A
grant is rejected for lifetime only when its requested expiration cannot fit
within Azure's maximum delegation-key interval of seven days from the requested
key start. The requested key expiration is capped approximately as follows:

```text
preferred key expiration
    max(now + target key lifetime, grant expiration + refresh margin)

requested key expiration
    min(preferred key expiration, maximum Azure key expiration)
```

A freshly returned key may issue the current grant when it covers the exact
requested grant expiration even if it lacks the preferred future refresh
margin. Such a key is simply not ideal for later cache reuse.

Azure's returned `UserDelegationKey.signed_start` and `signed_expiry` values,
not the requested key interval, are authoritative. Both values must be present,
parse as timezone-aware timestamps, and satisfy:

```text
signed_start <= current injected clock time
signed_expiry > signed_start
signed_expiry >= requested UploadGrant expiration
```

Missing, malformed, timezone-naive, or unusable returned lifetime data causes
the safe provider-neutral `UploadGrantError`. A generated SAS is never allowed
to expire after the authoritative `signed_expiry`; under normal conditions its
`UploadGrant.expires_at` remains the exact application-requested expiration.

The Blob SAS is scoped to one exact Blob, uses `protocol="https"`, omits a SAS
start time, and grants `BlobSasPermissions(create=True)` only. It does not grant
write, read, delete, add, tag, list, container, or prefix-wide access. The
resulting browser instructions are exactly:

```text
method:  PUT
header:  x-ms-blob-type: BlockBlob
target:  exact signed Blob URL
```

This contract intentionally assumes one direct HTTP `PUT` using Azure `Put
Blob`. Nexus's current 50 MiB upload maximum is appropriate for that single
request design. If a future browser uploader uses staged or chunked Azure
operations such as `Put Block` and `Put Block List`, the least-privilege
create-only permissions and Azure service-version behavior must be explicitly
revalidated. Nexus must not grant `write` now merely to anticipate that future
algorithm.

The SAS URL and delegation key are bearer credentials. They must not be logged,
persisted, or emitted to telemetry. Azure acquisition and signing failures are
translated to a fixed safe `UploadGrantError`; task cancellation remains
cancellation.

## Authorized upload initiation and trusted upload state

`InitiateFileUpload` is the provider-neutral Phase 8 application use case. It
accepts trusted organization and user public IDs plus untrusted upload metadata;
the client never supplies a storage key, creator identity, or tenant identity.
Its ordering is deliberate:

```text
check files.upload
        ↓
validate upload intent and generate storage_key
        ↓
calculate requested grant expiration
        ↓
issue and validate the effective upload grant
        ↓
construct File(PENDING) + FileUploadAttempt
        ↓
atomically persist both
        ↓
return File + ephemeral grant
```

The runtime permission check resolves the exact organization/user pair through
tenant-safe User, UserRole, Role, RolePermission, and Permission joins. The
Organization and User must be active and not deleted, the Role must not be
deleted, and the requested permission must be assigned. Missing or mismatched
state is a denial. The check is performed on every initiation and is not cached,
so RBAC changes affect the next request. It is a point-in-time decision: Nexus
does not hold a database transaction or row lock across the later provider call.

Provider I/O occurs before the short File write transaction. If grant issuance
fails, no permanent File state is created. If persistence fails, the signed
grant is never returned and expires naturally. The write transaction inserts
exactly one new pending File and one upload attempt atomically. The pending File
has `size_bytes=None` and `checksum_sha256=None`.

`FileUploadAttempt` stores only:

- the File and organization relationship;
- `declared_size_bytes` accepted by the upload-intent policy;
- the provider's effective `grant_expires_at`;
- the trusted creation timestamp.

The table never stores the signed URL, SAS query, required grant headers, User
Delegation Key, provider name, container, credential, actual size, checksum, or
security result. Its composite `(file_id, organization_id)` foreign key targets
the owning File and cascades when that File is deleted.

The schema deliberately allows more than one upload attempt for a File so it
does not block a future, explicitly designed grant-reissuance flow. Phase 8 does
not implement reissuance: every initiation creates one new File and exactly one
attempt. If reissuance is added later, asynchronous storage events must be
correlated deliberately with the responsible attempt. A worker must not assume
that the latest attempt caused a `BlobCreated` event because cloud events may be
delayed or delivered out of order. Reissuance must also preserve the trusted
declared metadata associated with the existing File. Attempt identifiers,
event identifiers, attempt statuses, and correlation fields remain deferred to
that later event/verification design.

File write transactions retain the existing cancellation-settlement guarantee.
If a commit completes while the awaiting request is cancelled, the pending File
and attempt may remain even though the caller did not receive the grant. Later
abandoned-pending cleanup owns that lifecycle; Phase 8 does not abandon an
in-progress commit or rollback.

The current local Azurite path uses HTTP plus a Shared Key connection string.
That path cannot exercise the production security chain:

```text
ManagedIdentityCredential
        ↓
Get User Delegation Key
        ↓
User Delegation SAS
```

Phase 7 validates the Azure implementation with focused unit tests. Controlled
deployment validation may add integration coverage against either a real Azure
Storage account or a separately verified, dedicated Azurite configuration
using OAuth and HTTPS that supports the required delegation behavior. Existing
connection-string Azurite tests must not be presented as proof of the Managed
Identity and User Delegation path. Nexus must never add a production Shared
Key, account-key SAS, or service SAS fallback to make local testing easier.

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
- blank names, `/`, `\`, Unicode `Cc` control characters, and the explicit
  bidirectional controls `LRE`, `RLE`, `LRO`, `RLO`, `PDF`, `LRI`, `RLI`,
  `FSI`, and `PDI` are rejected without rejecting all Unicode `Cf` characters;
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

Phases 5 and 6 define the provider-neutral preparation boundaries. Phase 8
composes them into authorized upload initiation without changing either
boundary; the client upload and verification steps remain future work:

```text
authenticate and authorize upload
        ↓
UploadIntentPolicy
        ↓
issue short-lived exact-object upload grant
        ↓
atomically persist File(PENDING) with size_bytes=None
and FileUploadAttempt with declared_size_bytes
        ↓
client uploads directly to object storage
        ↓
verify actual object size, type, checksum, and security state
        ↓
transition File to AVAILABLE or FAILED
```

The client never chooses the storage key. A successful object upload or a
provider event alone does not establish tenant ownership, authorization, or
File availability. Later verification must measure the actual object size and
enforce the configured maximum. Because Phase 8 preserves `declared_size_bytes`
in trusted persistent upload state, asynchronous verification must also compare
the actual size with that declaration. It must not use `File.size_bytes` for
the untrusted declaration; that field remains `None` while pending and records
only the verified final size when the File becomes available. Verification must
also inspect actual content type where required, compute integrity metadata,
and apply future malware/security policy.

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

Phase 6
    provider-neutral upload-grant contract (implemented)

Phase 7
    Azure User Delegation upload-grant adapter (implemented)

Phase 8
    authorized upload initiation and trusted upload state (implemented)

Phase 9
    upload-initiation HTTP API, configuration, and composition (future)
```

## Deferred work

Later phases own:

- upload-initiation HTTP schemas, controller, authentication-context mapping,
  grant-TTL configuration, composition wiring, and API idempotency decision;
- Azure upload-grant composition wiring;
- actual size, type, checksum, and security verification;
- File lifecycle transitions after storage verification;
- upload and management APIs;
- list, download, and delete use cases and APIs;
- retention and object cleanup;
- Document processing, chunks, embeddings, and RAG;
- frontend File workflows.
