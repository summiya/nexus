# File Domain Architecture

**Status:** Implemented Phase 1 foundation

## Purpose

The File capability owns metadata for a tenant-owned binary object. Phase 1
provides the domain record, persistence boundary, native async SQLAlchemy
adapter, and PostgreSQL schema. It does not upload, download, process, or expose
Files through an API.

## Boundary

```text
Future File application service
        ↓
FilePersistence
        ↓
SqlAlchemyFilePersistence
        ↓
AsyncSession / PostgreSQL
```

The File domain and persistence port do not depend on FastAPI, SQLAlchemy, or a
cloud provider. SQLAlchemy remains inside infrastructure.

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

## File and Document separation

```text
File
    binary object, ownership, and storage metadata

Document (future)
    parsed and indexable representation derived from a File
```

File does not own extracted text, pages, chunks, embeddings, retrieval state,
vector identifiers, or Document processing status.

## Deferred work

Later phases own:

- upload and object-storage ports/adapters;
- Azure Blob Storage and Azurite configuration;
- key generation and filename/upload validation;
- list, download, and delete use cases and APIs;
- retention and object cleanup;
- Document processing, chunks, embeddings, and RAG;
- frontend File workflows.
