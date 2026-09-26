# File Domain Architecture

**Status:** Implemented event-first direct browser upload initiation

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
originally added runtime RBAC enforcement and pre-upload persistence; the
event-first refactor removes that persistence because requesting a grant does
not prove that a Blob exists. Phase 9 exposes authenticated upload initiation
through a provider-neutral HTTP contract. File bytes still bypass Nexus. Phase
10 adds the protected Files screen and transfers one selected browser File
directly to Azure Blob Storage. A future BlobCreated worker, not upload
initiation, will create the pending File after accepting the committed Blob and
its protected Nexus context. Phase 11 defines the provider-neutral upload
completion event and a strict, SDK-free Azure BlobCreated CloudEvent mapper. It
does not wire event delivery or a worker into the application.

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
        ├── UploadGrantIssuer
        │       ↑
        │   AzureUserDelegationUploadGrantIssuer
        │       ↓
        │   Borrowed async BlobServiceClient
        │
        └── UploadContextProtector
                ↑
        AesGcmUploadContextProtector

File binary storage operations
        ↓
ObjectStorage
        ↑
AzureBlobObjectStorage
        ↓
Async Azure ContainerClient

Browser direct upload
        ├── initiateFileUpload()
        │       ↓ authenticated Nexus request
        │   POST /api/v1/files/uploads
        │
        └── Azure browser upload transport
                ↓ SAS only
            BlockBlobClient.uploadData(File)
                ↓
            Azure Blob Storage

Future committed-Blob persistence
        ↓
BlobCreated worker
        ├── UploadContextProtector.unprotect()
        └── FilePersistence.create_file()
                ↓
        AsyncSession / PostgreSQL

Phase 11 event boundary (not composed until the worker phase)
        Azure BlobCreated CloudEvent
                ↓
        AzureBlobCreatedEventMapper
                ↓
        UploadCompletionEvent
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
`declared_size_bytes`: it is untrusted request metadata. It is never copied
directly into `File.size_bytes`. The committed-upload worker independently
measures the current Blob and stores that verified actual size:

```text
ValidatedUploadIntent.declared_size_bytes
    untrusted client declaration

File(PENDING).size_bytes
    actual verified object size

File(AVAILABLE).size_bytes
    actual verified object size
```

During upload initiation, `ValidatedUploadIntent.declared_size_bytes` is copied
into the encrypted, authenticated `UploadContext` carried with the Blob. No File
row exists yet. When the worker accepts a committed Blob and its context, it
requires the actual size, protected declaration, and provider event size to
agree. Do not overload `File.size_bytes` with untrusted request metadata.

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
constructs its resources, exposes only `ObjectStorage` and `UploadGrantIssuer`,
and owns asynchronous cleanup. The root `AppContainer` owns this composition
for the FastAPI application lifetime. Azure SDK clients and credentials remain
inside infrastructure and composition.

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
- `AZURE_STORAGE_ACCOUNT_NAME` for the production User Delegation signer;
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

The configured account and container are explicit inputs. Phase 9 requires an
explicit nonblank account name when constructing the default production issuer;
it is never inferred from an Azure, sovereign-cloud, private, or custom endpoint
hostname. The opaque
`storage_key` is passed unchanged to `BlobServiceClient.get_blob_client()`, and
the adapter uses the returned `BlobClient.url` rather than constructing a Blob
URL manually. Composition builds it beside `AzureBlobObjectStorage` using the
same application-owned `BlobServiceClient`; it does not create a second client
or credential. Resource shutdown remains owned by `StorageComposition`. The
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

Phase 10 uses `@azure/storage-blob` `BlockBlobClient.uploadData(File)`. Files at
or below the configured single-shot threshold use `Put Blob`; larger Files use
SDK-managed `Put Block` requests followed by `Put Block List`. The adapter does
not manually generate block IDs, buffer the entire File, or implement its own
request scheduler.

Create-only `c` permission supports the new-Blob `Put Block` and `Put Block
List` flow only with Azure Storage service version `2026-04-06` or later.
Compatibility is enforced on both sides of the direct transfer:

```text
backend-generated SAS:  sv >= 2026-04-06
browser SDK requests:   x-ms-version >= 2026-04-06
```

The backend continues to grant create only. It does not grant write, read,
delete, or list access. Focused no-network contract tests exercise the real
Python SAS signer and real browser SDK version header so dependency changes
cannot silently weaken this requirement.

The SAS URL and delegation key are bearer credentials. They must not be logged,
persisted, or emitted to telemetry. Azure acquisition and signing failures are
translated to a fixed safe `UploadGrantError`; task cancellation remains
cancellation.

## Authorized upload initiation and protected upload context

`InitiateFileUpload` accepts trusted organization and user public IDs plus
untrusted upload metadata; the client never supplies a storage key, creator
identity, or tenant identity. Its ordering is deliberate:

```text
check files.upload
        ↓
validate upload intent and generate storage_key
        ↓
generate reserved File public UUID
        ↓
issue and validate the effective upload grant
        ↓
construct and protect UploadContext
        ↓
return ephemeral upload instructions
```

The runtime permission check resolves the exact organization/user pair through
tenant-safe User, UserRole, Role, RolePermission, and Permission joins. The
Organization and User must be active and not deleted, the Role must not be
deleted, and the requested permission must be assigned. Missing or mismatched
state is a denial. The check is performed on every initiation and is not cached.
It may use a short PostgreSQL read, but initiation opens no File write
transaction and creates neither a File nor an upload-attempt row.

The immutable `UploadContext` contains its schema version, reserved File public
UUID, organization and creator public UUIDs, exact opaque storage key,
normalized filename and MIME metadata, declared size, issue time, and the
provider's effective grant expiration. It contains no Azure account, container,
URL, SAS, event ID, request ID, or provider credential. The browser treats it as
opaque.

`UploadContextProtector` is the narrow application-facing protection boundary.
The infrastructure implementation uses AES-256-GCM with a fresh 96-bit nonce.
Its compact Base64URL envelope contains a format version, the non-secret key ID
`primary`, nonce, and ciphertext with authentication tag. Format version and key
ID are authenticated as associated data. The encrypted payload also carries its
schema version. Unknown versions or key IDs, malformed envelopes, wrong keys,
and tampering all produce the same fixed safe error.

`FILE_UPLOAD_CONTEXT_KEY` is required, represented as `SecretStr`, and must be a
Base64URL encoding of exactly 32 bytes. The repository example contains only an
explicitly labelled deterministic development key; production must override it
through secret injection or Key Vault. The key is never logged, returned, or
included in error text. This phase uses one key only: the envelope key ID avoids
a future format migration, but no key ring or automatic rotation exists yet.

The protected context is capped at 4 KiB and stored as the single Blob metadata
entry `nexus_upload_context`, comfortably inside Azure's 8 KiB total metadata
limit. Decoding validates authenticity, schema, versions, and field invariants.
It deliberately does not reject a context because worker processing occurs
after `grant_expires_at`: a Blob may commit before grant expiry and its event may
arrive later. Azure enforces the grant at commit time; the event occurrence time
remains diagnostic rather than a replacement authorization check.

If grant issuance or protection fails, no permanent File state exists. A grant
created before a later protection or response failure is never returned and
simply expires. Cancellation or abandonment before upload likewise leaves no
File row.

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

## Upload-initiation HTTP API

The API exposes the use case as:

```text
POST /api/v1/files/uploads
        ↓
CurrentAuthContextDep
        ↓
InitiateFileUpload
        ↓
200 OK
```

The JSON request contains only `original_name`, nullable `mime_type`, and
`size_bytes`. Organization and user identity always come from the trusted
authentication context. The transport maps `size_bytes` to the application's
`declared_size_bytes`; it never populates `File.size_bytes` from this untrusted
declaration. The controller delegates authorization, semantic validation,
storage-key generation, grant issuance, and context protection to the
application service.

The response contains only generic upload instructions: URL, method, required
headers, the one protected metadata value, and expiration. It contains no File
representation because no File exists yet. It also excludes the raw storage
key, tenant and creator identities, declared size, provider, and container.
Signed URLs, required headers, and protected context remain opaque and are
returned without normalization. Successful responses use `Cache-Control:
no-store` because they contain short-lived bearer capability material.

`POST /files/uploads` defines no `Idempotency-Key` contract. A retry creates a
new storage key, reserved File UUID, context, and grant, but still no database
row. Unused grants expire without abandoned PostgreSQL state.

`FILE_UPLOAD_GRANT_TTL_SECONDS` is an application security policy with a
default of 600 seconds and a maximum of 3600 seconds. It remains separate from
Azure User Delegation Key caching and lifetime limits.

In Managed Identity mode, composition supplies the production User Delegation
issuer. The existing local/test connection-string path deliberately supplies an
unavailable issuer unless a controlled issuer is explicitly injected, so upload
initiation safely returns service unavailable rather than generating an
account-key SAS. This keeps local application startup usable without weakening
the production authentication model.

The endpoint handles metadata only. It does not accept multipart data or proxy
the binary body. Direct browser upload also requires Azure Storage CORS for the
frontend origin, `PUT`, and the required provider headers; FastAPI CORS does not
configure that provider boundary, and Nexus runtime does not provision it.

## Direct browser upload

Phase 10 exposes the protected `/files` route and uploads one browser `File` at
a time:

```text
select File
        ↓
client UX check: declared size <= 536,870,912 bytes
        ↓
authenticated POST /api/v1/files/uploads
        ↓
ephemeral upload instructions + protected context
        ↓
BlockBlobClient(signed URL).uploadData(File)
        ↓
Put Blob OR Put Block × N + Put Block List
        ↓
committed Blob contains nexus_upload_context metadata
```

The browser uses an 8 MiB block size, concurrency of four, and a 64 MiB
single-shot threshold. The original `File` is handed directly to the Azure SDK;
Nexus does not call `arrayBuffer()`, encode it as base64, or otherwise hold a
second whole-file representation in memory. SDK chunking is a transfer
strategy, not resumability: a page reload or explicit retry starts a new Nexus
upload initiation.

The current upload grant is accepted only when its method is exactly `PUT` and
its only upload-control instruction is `x-ms-blob-type: BlockBlob` (header-name
matching follows HTTP case-insensitivity). It also requires exactly one nonblank
`nexus_upload_context` metadata value. The Azure SDK owns the headers for
`Put Blob`, `Put Block`, and `Put Block List`; provider instructions are not
blindly attached to every block request. New required upload-control headers
must be deliberately implemented rather than silently ignored.

The upload grant is an ephemeral bearer capability. It moves directly from the
validated initiation response to the Azure transport and is never placed in
React Query, Zustand, browser storage, route state, telemetry, error text, or
the UI. The protected context is likewise kept out of UI/global state/logging
and passed opaquely to the Azure SDK. The Nexus Bearer token is used only for
the Nexus control-plane request; Azure receives only the SAS URL and protected
metadata. Raw Azure errors are replaced with fixed safe frontend feedback.

One active transfer owns one `AbortController`. Cancellation and component
unmount abort the request and suppress stale UI callbacks. No File row exists to
delete, and cancellation does not promise immediate removal of uncommitted
blocks.
There is no automatic retry system, resumability, multi-file queue, or global
upload store in this phase.

Successful browser transfer means only:

```text
browser transfer complete
        ↓
Nexus awaits BlobCreated processing and verification
```

It never means that the File is verified, safe, or available.

### Azure Blob CORS deployment requirement

Blob-service CORS is deployment configuration and is not provisioned by Nexus
runtime. Each environment must allow the exact authorized frontend origin and
`PUT`. Production must not use a wildcard origin. Allowed request headers must
cover `content-type` and the Azure SDK's required `x-ms-*` headers, including
`x-ms-version`, `x-ms-client-request-id`, `x-ms-blob-type`, and
`x-ms-blob-content-type`, plus `x-ms-meta-nexus_upload_context`. Exposed response
headers should be limited to those
operationally required, such as `etag`, `x-ms-request-id`, `x-ms-version`, and
`x-ms-client-request-id`, with a sensible preflight cache duration.

The local Shared Key and HTTP Azurite path does not prove the production Managed
Identity, User Delegation SAS, HTTPS, or exact-origin CORS path. Release
validation must use a controlled Azure environment to exercise both a small
single-shot upload and a File larger than 64 MiB, reject an unauthorized
origin, confirm that no Nexus Authorization header reaches Azure, and confirm
that the committed Blob carries the protected context metadata.

### Production-hardening release gate

Phase 10 completes direct browser transfer capability, but the complete File
upload feature is not yet hardened for unrestricted or public production
traffic. Frontend size validation and server-side declared-size validation are
not authoritative security controls. Phase 14 independently verifies stored
size; later phases must still add:

- content and MIME verification;
- security and malware checks where applicable;
- cleanup of oversized or otherwise invalid stored objects;
- cleanup/reconciliation for committed objects whose events cannot be processed;
- provider lifecycle handling for abandoned uncommitted blocks;
- upload-initiation abuse protection, rate limiting, or equivalent quota
  controls.

Those controls are intentionally not implemented in Phase 10. The release
invariant remains:

```text
browser transfer complete -> committed Blob; File row may not exist yet
worker acceptance         -> File PENDING with verified actual size
security verification     -> File AVAILABLE or FAILED
```

Only verified `AVAILABLE` Files may enter later Document processing or RAG
ingestion.

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
must not exceed `FILE_UPLOAD_MAX_SIZE_BYTES`. Nexus's maximum individual File
size is 512 MiB (536,870,912 bytes), and zero-byte uploads are valid. During
upload initiation, this limit applies only to the untrusted declared size; it
does not prove the object's actual size and is not an object-storage capability
limit. Later upload verification must independently enforce that the actual
stored object size is no greater than 536,870,912 bytes before a File can
become `AVAILABLE`.

The generated `files/<uuid4 hex>` key is 38 provider-portable ASCII characters
using lowercase hexadecimal plus `/`. Nexus performs no database or storage
existence preflight and no deduplication. The database uniqueness constraint
and create-only object storage semantics remain the final collision defenses.

Generation uses UUID4 randomness, but canonical syntax validation deliberately
checks only `files/<32 lowercase hexadecimal characters>`. Consumers do not
parse the suffix or infer UUID version semantics. Storage-key structure is
object identity, not tenant authorization.

Validation failures use one application error contract with fixed,
non-sensitive messages. Invalid filenames, MIME values, and sizes are never
echoed into an error. Transport-specific error mapping belongs to the later
File API phase.

## Upload completion event boundary

`UploadCompletionEvent` is the provider-neutral boundary between a trusted
storage-provider delivery and future File processing. It contains exactly:

```text
event_id
source
storage_key
occurred_at
entity_tag
reported_size_bytes
```

`(source, event_id)` is a stable logging and correlation identity. It is not a
durable correctness or deduplication boundary. `source` is a stable Nexus
namespace such as `azure-primary` or `reconciliation`, not an Azure resource
identifier that application code interprets. Correctness across Event Grid
delivery, Service Bus redelivery, DLQ replay, and reconciliation depends on the
Phase 14 File business-identity and immutable-ownership checks required by
`INV-REL-004`. `entity_tag` is an opaque object-version identity.
`reported_size_bytes` is provider-reported information and is never a
substitute for later measurement of the current object.

`occurred_at` is diagnostic, audit, and secondary consistency information. It
is not a primary authorization control. The provider enforces SAS validity when
the object commit occurs, and delayed event delivery must not be confused with
a post-expiration commit.

The pure `AzureBlobCreatedEventMapper` accepts an already-decoded CloudEvents
1.0 mapping. It validates the exact configured Azure event source and container,
`Microsoft.Storage.BlobCreated`, Block Blob type, supported `PutBlob` or
`PutBlockList` APIs, bounded identifiers, aware occurrence time, nonnegative
reported size, and the canonical `files/<32 lowercase hex>` namespace. It
derives the storage key only from the validated CloudEvent subject. It never
uses `data.url` as object identity or as network input. JSON property order has
no meaning.

The Azure CloudEvent source comparison is exact. Azure resource IDs are
case-insensitive, so Phase 12 must take `expected_source` from a captured real
event or deliberately switch the comparison to case-insensitive semantics.

The mapper performs no network, database, queue, or Azure SDK operation. It is
not wired into application composition in Phase 11; the worker phase will own
delivery integration and composition.

## Durable Azure upload-completion routing

Phase 12 routes committed File objects through shared Azure source
infrastructure without adding an application queue abstraction:

```text
canonical File Blob container
        ↓ Microsoft.Storage.BlobCreated
shared Event Grid system topic
        ↓ Nexus-owned File event subscription
regional Service Bus Premium queue
        ↓
Phase 13 worker
```

Nexus launches with one Premium namespace partition and one Messaging Unit.
The queue is shared across organizations, has an 80-GiB capacity, and buffers
upload bursts independently of future worker throughput. Partition count is an
explicit immutable namespace-creation choice; changing it requires a new
namespace and controlled infrastructure migration. MU capacity is adjusted
from measured CPU, memory, queue depth, processing lag, and message throughput,
not from registered-user count.

The storage-account system topic is shared source infrastructure because Azure
permits one system topic per source. Deployment must explicitly reference an
existing topic or separately create a new shared topic; it must never discover
and adopt infrastructure implicitly. The File capability owns only its event
subscription. Permissions to create or alter subscriptions on the shared topic
are security-sensitive and must be limited to audited deployment/operations
identities: a subscription can deliver using the topic's Managed Identity into
an authorized destination.

Deployment resolves the configured Nexus storage account and fails closed
unless the selected system topic has that exact account resource ID as its
source and `Microsoft.Storage.StorageAccounts` as its topic type. It also
requires a usable system-assigned Managed Identity principal. The Service Bus
resource location is derived directly from the source storage-account region,
not supplied independently. The topic's Managed Identity is not granted queue
or dead-letter access until those trusted source and identity invariants pass.

The File event subscription delivers CloudEvents 1.0, includes only
`Microsoft.Storage.BlobCreated`, and applies the case-sensitive subject prefix
`/blobServices/default/containers/<file-container>/blobs/files/`. It does not
filter `data.api` or `data.blobType`; the Phase 11 mapper remains the strict
semantic boundary. The system-topic identity receives only queue sender access
and dead-letter-container write access. Service Bus local authentication is
disabled, TLS 1.2 or later is required, and the firewall permits Event Grid
through trusted Microsoft service delivery while still requiring Managed
Identity authorization.

The queue enables a ten-minute duplicate-detection window. Event Grid's
Service Bus internal `MessageId` is expected to remain stable across redelivery,
and `aeg-output-event-id` carries the Event Grid event ID. Controlled Azure
validation must verify that behavior before it is relied on operationally.
Duplicate detection is only load reduction. Phase 13 provides safe transport
settlement, while Phase 14 business idempotency provides correctness.

Event Grid retries for at most 30 attempts or 24 hours and then uses the private
`event-grid-deadletter` container. That container is outside the configured
File-container subject prefix. A dead-letter Blob must never feed back into the
File completion queue.

### Orphan reconciliation release gate

Nexus keeps one canonical File container. It does not move every successful
upload through incoming and permanent containers. Before unrestricted public
upload traffic is enabled, a reviewed reconciliation process must exist for
sufficiently old committed Blobs that have no legitimate File state. It must
classify candidates for recovery, quarantine, or deletion and, at scale, use an
inventory or change-driven approach rather than frequent full-container scans.

Abandoned block uploads may leave uncommitted blocks. Azure ordinarily garbage
collects them about seven days after the last successful block operation, but
the staged bytes occupy storage during that period and associated operations
and capacity can incur cost. Phase 12 adds no custom uncommitted-block cleanup;
the retention and billing exposure remain part of the production capacity and
abuse review.

### Phase 13 settlement and DLQ requirements

`AzureBlobCreatedEventMappingError` is a permanent semantic message failure.
Phase 13 must immediately dead-letter it with the fixed bounded reason
`INVALID_BLOB_CREATED_EVENT`. Its normal expected baseline is zero. Every
occurrence must emit a structured log or metric with safe correlation.
Monitoring must raise one grouped operational/security alert when the count is
at least one during a short monitoring window; additional occurrences in that
window increment logs and metrics without paging once per message. The worker
must not expose the unrestricted provider payload, SAS data, protected
UploadContext, secrets, or internal details in DLQ reason text. Temporary
storage, database, Key Vault, and network failures may use retry/abandon
behavior.

The Phase 13 worker accepts only AMQP `DATA` message bodies containing a
strictly decoded JSON object. Nexus limits the aggregate body to 64 KiB
(65,536 bytes), independently of the larger Service Bus queue limit. Invalid
UTF-8, JSON, body form, or size is immediately dead-lettered with the fixed
reason `INVALID_MESSAGE_BODY`.

Unexpected application-handler failures are explicitly abandoned. After an
abandon attempt, the worker waits before receiving another message using a
process-local jittered exponential delay: two seconds nominal initially,
doubling to a 60-second cap, with every actual wait between one-half and all of
its nominal value. A successful handler execution resets the delay. This is a
receive-loop delay, not a retry of the same delivery, a circuit breaker, or a
second scheduling system.

Recoverable Service Bus connection failures recreate the receiver after a
bounded delay. Authentication, authorization, missing-entity, and
disabled-entity failures are fatal configuration/security conditions: the
worker logs only their exception type and terminates instead of reconnecting
indefinitely.

The worker renews a PeekLock for at most five minutes and processes one message
at a time. Upload-completion handling must remain short. Malware scanning, OCR,
extraction, chunking, embeddings, RAG, and other long-running work must be
scheduled outside the upload-completion delivery.

On graceful SIGTERM or SIGINT, the worker stops receiving and gives an
in-flight handler up to ten seconds to finish. Successful work completed within
that bound is completed normally. Handler failure is abandoned immediately; if
the grace period expires, the handler is cancelled and the worker attempts to
abandon the message so another replica can receive it promptly. Shutdown
abandon does not trigger the failure cooldown. Lock loss or any complete,
abandon, or dead-letter settlement failure is never reported as successful
processing.

Phase 13 stores no transport-level delivery receipt. Phase 14 supplies the real
`UploadCompletionHandler`: it performs Blob access and UploadContext decryption
without a database transaction, then applies the File business effect in one
short transaction protected by `INV-REL-004`.

Service Bus DLQ messages do not observe TTL and are not automatically removed.
Phase 13 operations must therefore define inspection, safe replay, and explicit
purge procedures and alert on DLQ size. A valid message exhausted by a prolonged
dependency outage may be replayed only after the dependency is healthy and the
operator has confirmed the bounded body is a legitimate original delivery.
Replay must preserve the original event body and correlation identity; Phase 14
business idempotency makes repeated delivery safe. Permanently invalid messages
remain quarantined for investigation and must not be replayed unchanged. Phase
12 implements none of that worker or settlement behavior; it records the
non-negotiable operational boundary.

Event delivery is assumed to be at least once and unordered. Redelivery,
worker restart, and concurrent workers are normal. Correctness cannot depend on
one worker, process memory, arrival order, exactly-once delivery, or Service Bus
duplicate detection.

For Azure Event Grid, a future producer uses its configured Nexus source and
the provider CloudEvent ID. A reconciliation producer should derive a stable,
deterministic ID from a versioned canonical representation of `storage_key` and
`entity_tag`. Replaying the same original DLQ message preserves its original
source and event ID; reconstructing an event from storage is a new
reconciliation source. The same object version may therefore have different
delivery identities across sources. Only business identity deduplicates across
those sources.

After the worker authenticates the protected `UploadContext`, it must
classify File business identity using both `file_public_id` and `storage_key`
plus immutable ownership:

| Existing identity state | Required outcome |
|---|---|
| Neither identity exists | New File candidate |
| Both identify the same File and ownership is consistent | Idempotent duplicate success |
| Only `file_public_id` exists | Anomaly: reject and alert |
| Only `storage_key` exists | Anomaly: reject and alert |
| The identities identify different Files | Severe anomaly: reject and alert |
| Both identify the same File but ownership differs | Security/data anomaly: reject and alert |

Ownership comparison includes at least `organization_public_id` and
`created_by_user_public_id`. No existing File may be overwritten, reassigned,
or adopted to resolve an anomaly. A unique-constraint violation alone is never
proof of a duplicate. After such a race, the failed transaction must be rolled
back, a fresh transaction started, and both identities plus ownership re-read
before classification.

The UploadContext protection key is the cryptographic trust anchor for tenant
and creator ownership claims carried in protected object metadata. If the key
is compromised, an attacker who can also create a Nexus-controlled storage
object could forge otherwise-authentic UploadContext ownership claims.

That trust anchor does not replace the additional future controls: trusted
event source and container validation, `event.storage_key ==
UploadContext.storage_key`, organization and user database revalidation,
current-object/ETag verification, and actual object verification. Production
readiness also requires Key Vault or equivalent secret injection, key-ID-based
rotation with old-key decryption overlap, handling for objects created under
retiring keys, and a documented compromise response. Phase 11 adds none of
that key-management infrastructure.

## Committed-upload verification and registration

Phase 14 reads the current Blob properties through the provider-neutral
`ObjectStorage` boundary. Azure ETags are normalized only by removing expected
surrounding quotes; weak and strong ETag semantics are otherwise preserved. A
missing Blob is an obsolete successful no-op, while an ETag mismatch is a stale
successful no-op. These outcomes use distinct safe structured log events so
their rates can be observed without logging storage keys, metadata, names, or
provider details.

For a current Blob, the worker decrypts `nexus_upload_context`, binds it to the
event storage key, and requires the actual Blob size, protected declared size,
and event-reported size to match. The verified actual size must not exceed
`FILE_UPLOAD_MAX_SIZE_BYTES`. The API and worker read this same setting and
deployment must keep their values identical; otherwise the API may authorize an
upload that the worker later rejects permanently.

Only after external verification does one short PostgreSQL transaction resolve
the exact organization/creator relationship and apply `INV-REL-004`. New Files
are inserted as `PENDING` with the verified actual `size_bytes` and no checksum.
An exact identity-and-ownership duplicate succeeds without mutation. Partial,
divergent, or ownership-conflicting identities are permanently rejected and
dead-lettered as `INVALID_UPLOAD_COMPLETION`. Expected unique races roll back
and reclassify both identities in a fresh transaction; unrelated integrity
failures remain transient database failures.

The worker uses a deliberately small PostgreSQL pool because each process
handles one message at a time. Its initial defaults are pool size two and zero
overflow; deployments may tune these narrow settings while accounting for the
total pool capacity of all worker replicas.

Phase 14 does not delete permanently rejected Blobs. They accumulate in the
canonical container until the required reconciliation process classifies them
for recovery, quarantine, or deletion.

## Defender malware scanning and File availability

Phase 15 uses Microsoft Defender for Storage on-upload malware scanning as the
managed security scanner. Defender publishes scan results to a dedicated Event Grid custom topic; Nexus
routes those events into a dedicated malware-result Service Bus queue while the
existing File worker process consumes both queues with shared resources. Blob index-tag scan
result writes are disabled, so File availability does not trust mutable Blob tags.

The Azure infrastructure mapper validates the expected custom-topic resource ID,
Defender malware-result event type, known schema metadata, configured storage
account and File container, canonical storage key, and ETag. The Blob URI in the
provider payload is never used as object identity or as network input. Nexus
accepts Defender result data versions 1.0 and 1.1 and fails closed on unknown
versions.

Before changing File state, the application reads current Blob properties and
requires the scan-result ETag to identify the current Blob version. A missing
Blob or stale ETag is an obsolete successful no-op. A malware result can race
ahead of Phase 14 File registration; a missing File row is therefore retryable
rather than successful.

The terminal lifecycle is:

```text
PENDING + clean scan       -> AVAILABLE
PENDING + malicious scan   -> FAILED
PENDING + scan error       -> FAILED
PENDING + not scanned      -> FAILED
same terminal replay       -> idempotent success
opposite terminal result   -> permanent conflict
```

The database transition locks the File row by `storage_key` and applies the
state change in one short transaction. A malicious File remains stored with
status `FAILED`; Phase 15 does not delete or quarantine the Blob. Any download
or content-serving path must authorize and serve only Files whose storage status
is `AVAILABLE`.

A File can remain `PENDING` indefinitely if Defender scanning is capped or
disabled, or if the scan result is never successfully delivered. Production
reconciliation therefore requires PENDING-age metrics and alerting rather than
assuming every PENDING row will eventually transition.

Scan results can also arrive for Blob uploads that Phase 14 rejected before a
File row was created. Those scan messages cannot resolve a File, will retry, and
may ultimately reach the malware-result DLQ. That is expected operational noise
for rejected uploads and should be classified separately from unexpected
malware-processing failures. Phase 15 adds no custom antivirus,
quarantine/delete workflow, MIME sniffing, checksum persistence, Document
processing, OCR, chunks, embeddings, or RAG.

## File metadata read API and pagination

Phase 16 exposes authenticated File metadata through `GET /files` and
`GET /files/{file_public_id}`. Read authorization uses the existing
`files.read` permission, and every persistence query applies the organization
boundary in SQL. An unknown File and a File owned by another organization are
therefore indistinguishable to the caller.

The current File model has organization ownership but no project relationship.
Phase 16 remains organization-scoped rather than introducing a speculative
project field or authorization rule. Project-scoped File reads should be added
only when the File model gains an explicit project relationship.

Listing uses newest-first keyset pagination over
`(organization_id, created_at, public_id)`, matching the existing database
index. The HTTP cursor is opaque and versioned, page size is bounded, and the
query requests `limit + 1` rows to determine whether another page exists.
There is no `COUNT(*)` dependency and no offset pagination, so deep pages do
not become progressively more expensive as File volume grows.

Read responses expose only safe File metadata: public identity, original name,
MIME type, verified size when known, lifecycle status, and timestamps. They do
not expose internal database IDs, organization/creator IDs, storage keys,
checksums, provider URLs, Blob metadata, or credentials. PENDING and FAILED
Files may be visible as metadata to an authorized caller, but content-serving
and download paths must continue to serve only AVAILABLE Files.

## Files Library frontend contract

Phase 17 consumes the Phase 16 File metadata API with backend-driven cursor
pagination. The frontend treats the cursor as opaque, keeps only the small local
history required for Previous/Next navigation, and never reconstructs a cursor
from File metadata.

The Files frontend validates successful API responses with strict Zod schemas.
This is intentionally fail closed: unknown response fields and unknown
`storage_status` values cause the Library to show its safe error state instead
of silently rendering an unsupported contract. Backend response additions and
new File storage-status values therefore require a compatible frontend to be
deployed before or together with the backend change.

Page navigation uses React Query v5 `placeholderData: keepPreviousData`. The
current rows remain visible while the next or previous cursor page is loading,
and navigation controls are disabled while placeholder/fetching data is active.
The Library does not use offset pagination, infinite scrolling, total-count
queries, polling, or frontend-generated cursors.

Pending Files are presented as an expected security-verification state with
visible explanatory copy ("Being checked for security"), rather than as a
generic broken/loading state.

## Future upload and verification lifecycle

Phases 5 and 6 define the provider-neutral preparation boundaries. The current
application composes them into authorized, event-first upload initiation. Phase
10 implements direct client transfer; event consumption and verification remain
future work:

```text
authenticate and authorize upload
        ↓
UploadIntentPolicy
        ↓
issue short-lived exact-object upload grant
        ↓
protect Nexus UploadContext; no PostgreSQL File write
        ↓
client commits Blob with protected context metadata
        ↓
BlobCreated → Event Grid → Service Bus → worker
        ↓
validate source/blob/context and storage-key binding
        ↓
create File(PENDING) with verified actual size_bytes
        ↓
verify managed malware/security result
        ↓
clean → AVAILABLE; unsuccessful/malicious → FAILED
```

The client never chooses the storage key. A successful object upload or a
provider event alone does not establish tenant ownership, authorization, or
File availability. Later processing must verify the event source, account,
container and event type, fetch Blob properties, unprotect the context, compare
the actual Blob key with `context.storage_key`, and re-check organization/user
validity. Verification must measure actual object size, enforce the configured
maximum, and compare it with the protected declaration. `File.size_bytes`
records that verified actual size while pending. Business
deduplication follows the complete identity and ownership classification above;
delivery deduplication alone cannot establish successful prior processing.

Abandoned initiation needs no PostgreSQL cleanup. A partial uncommitted upload
has no File row. A committed Blob whose event cannot be processed is a future
dead-letter/reconciliation concern. Historical pending rows created by the old
pre-event lifecycle are preserved by the removal migration and require an
explicit deployment audit rather than guessed or destructive conversion.

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
    upload-initiation HTTP API, configuration, and composition (implemented)

Phase 10
    direct browser upload, progress, cancellation, and Files route (implemented)

Pre-event persistence refactor
    protected upload context and File creation deferred until BlobCreated
    processing (implemented)
```

## Deferred work

Later phases own:

- MIME/content-type verification and checksum generation where later justified;
- oversized and invalid-object cleanup;
- committed-Blob event dead-letter handling and reconciliation;
- upload-initiation abuse protection, rate limiting, or quota enforcement;
- upload and management APIs;
- list, download, and delete use cases and APIs;
- retention and object cleanup;
- Document processing, chunks, embeddings, and RAG;
- richer frontend File workflows such as listing, multi-file upload,
  drag-and-drop, and resumability.
