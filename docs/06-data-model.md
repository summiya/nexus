# Nexus AI — Data Model & Persistence Architecture

**Document:** `docs/06-data-model.md`  
**Document Type:** Canonical Technical Specification  
**Document Status:** Implementation Baseline  
**Version:** 1.1  
**Audience:** AI coding agents, backend engineers, architects, security engineers, DevOps engineers, database engineers  

## Technology Decisions

**Primary Backend:** Python + FastAPI  
**Primary Database:** Azure Database for PostgreSQL — Flexible Server  
**Vector Search:** pgvector PostgreSQL extension  
**Cloud Platform:** Microsoft Azure  
**Object Storage:** Azure Blob Storage  
**Cache & Transient Infrastructure:** Azure Managed Redis  
**Secret Management:** Azure Key Vault  
**AI Provider Layer:** Nexus Model Gateway  
**AI Providers:** Azure OpenAI, OpenAI, Anthropic, and future providers  
**ORM:** SQLAlchemy  
**Database Migrations:** Alembic  

## Architectural Authority

This document is the canonical data-model and persistence specification for Nexus AI.

AI coding agents MUST follow the architecture, ownership rules, relationship rules, isolation boundaries, storage rules, persistence decisions, and table conventions defined in this document.

AI coding agents MUST NOT introduce a new database, storage system, vector database, ORM, identifier strategy, or persistence technology without an explicit architecture decision.

PostgreSQL is the authoritative system of record for Nexus.

pgvector is an extension running inside PostgreSQL and is NOT a separate database.

Azure Blob Storage is used for large binary files and generated artifacts.

Azure Managed Redis is used only for cache, rate limiting, queues, locks, idempotency, and other transient infrastructure state.

Azure Key Vault is used for secrets and credentials.

AI providers are accessed through the Nexus Model Gateway rather than being called directly throughout the application.

---

# 1. Purpose

This document defines the canonical initial domain model and persistence architecture for Nexus AI.

AI coding agents MUST treat this document as the source of truth when creating:

- SQLAlchemy models
- Alembic migrations
- Pydantic schemas
- Repository classes
- Service-layer methods
- Authorization checks
- Database constraints
- Row-Level Security policies
- Storage paths
- Background jobs
- Vector-search queries
- Audit logging
- Usage tracking
- API endpoints

The implementation MUST NOT introduce a different primary database, object-storage model, tenant hierarchy, identifier pattern, or lifecycle convention without an explicit architecture decision.

---

# 2. Nexus Product Context

Nexus is an AI platform built around:

- Users
- Organizations
- Workspaces
- Projects
- Conversations
- Messages
- Files
- Documents
- Knowledge bases
- Models
- Providers
- Agents
- Tools
- MCP servers
- Workflows
- Artifacts
- Audit events
- Usage records

The platform must support:

1. Multi-tenancy
2. Project-level isolation
3. Role-based access control
4. AI model routing
5. Multiple model providers
6. Agent orchestration
7. Tool execution
8. MCP integration
9. RAG/knowledge retrieval
10. Workflow execution
11. File and artifact generation
12. Usage/cost tracking
13. Security auditing
14. Background processing
15. Future enterprise capabilities

---

# 3. Technology and Persistence Decisions

## 3.1 Primary database

Use:

**PostgreSQL**

In Azure production:

**Azure Database for PostgreSQL — Flexible Server**

PostgreSQL is the system of record for Nexus.

It stores:

- Identity references
- Organizations
- Memberships
- Workspaces
- Projects
- Conversations
- Messages
- File metadata
- Documents
- Document chunks
- Embeddings
- Knowledge bases
- Providers
- Models
- Agents
- Tools
- MCP servers
- Workflows
- Artifacts metadata
- Audit events
- Usage records
- Permissions
- Configuration
- Version information

PostgreSQL is authoritative.

If Redis, Blob Storage, or another system disagrees with PostgreSQL about domain ownership, PostgreSQL wins.

## 3.2 Canonical table design conventions

Unless an entity section explicitly documents a justified exception, durable Nexus domain tables MUST follow this baseline.

### Identifiers

Every normal domain table MUST have:

```text
id BIGINT PRIMARY KEY GENERATED/AUTOINCREMENT
public_id UUID NOT NULL UNIQUE
```

Rules:

- `id` is the internal relational identifier.
- `id` is used for primary keys, foreign keys, joins, indexes, and internal persistence relationships.
- `public_id` is the externally safe stable identifier exposed by APIs, URLs, events, and client-visible references.
- `public_id` MUST be UUID-based, non-null, unique, and indexed.
- Application code MUST NOT expose sequential internal `id` values as public resource identifiers.
- Foreign keys SHOULD reference the internal `id` unless an explicit architecture decision requires otherwise.
- New SQLAlchemy models MUST implement this dual-identifier pattern by default.

### Lifecycle fields

Normal mutable domain tables MUST include:

```text
created_at TIMESTAMP WITH TIME ZONE NOT NULL
updated_at TIMESTAMP WITH TIME ZONE NOT NULL
deleted_at TIMESTAMP WITH TIME ZONE NULL
```

Rules:

- `created_at` records durable creation time.
- `updated_at` records the last durable mutation time.
- `deleted_at` is the standard soft-delete marker for resources that support recovery, retention, or auditability.
- `created_at` and `updated_at` MUST be timezone-aware.
- `deleted_at` MUST remain nullable and MUST NOT be used as a substitute for immutable audit history.
- Append-only entities such as `AuditEvent` and `UsageRecord` may omit `updated_at` and `deleted_at` where their entity section explicitly defines append-only behavior.
- Association/junction tables may omit `deleted_at` when lifecycle semantics do not require soft deletion, but they MUST still follow the internal `id` convention unless explicitly documented otherwise.

### Required default review for every new table

When an AI coding agent or engineer designs a new persistence table, they MUST explicitly evaluate and document whether the table needs:

```text
id
public_id
created_at
updated_at
deleted_at
organization_id
workspace_id
project_id
created_by
status
```

The identifier and timestamp conventions above are the default. Scope, ownership, actor, and status fields depend on the domain entity.

Do not silently omit baseline fields. If a table intentionally deviates, the reason should be visible in the entity specification or architecture decision.

---

# 4. PostgreSQL + pgvector

Nexus will initially use **pgvector inside PostgreSQL**.

Do NOT introduce Pinecone, Weaviate, Milvus, Qdrant, Chroma, or another dedicated vector database for the initial architecture.

Reasons:

- One authoritative database
- Strong tenant filtering
- Strong project filtering
- Relational joins
- Transactional metadata
- Easier backups
- Easier local development
- Lower operational complexity
- Natural integration with document metadata
- Easier authorization enforcement

The embedding is stored with the document chunk.

Conceptually:

```text
Document
   │
   └── DocumentChunk
          ├── content
          ├── metadata
          ├── embedding
          ├── embedding_model_id
          └── project_id
```

Vector searches MUST be scoped before results are returned.

Never perform:

```text
vector search → retrieve arbitrary chunks → authorize later
```

Use:

```text
authorization context
      ↓
organization filter
      ↓
project / knowledge-base filter
      ↓
vector similarity search
      ↓
authorized results
```

---

# 5. Azure Storage Architecture

Nexus is Azure-first.

## 5.1 Azure Blob Storage

Use Azure Blob Storage for large binary objects.

Store:

- User-uploaded PDFs
- DOCX files
- Images
- CSV files
- Audio/video files where applicable
- Generated reports
- Generated spreadsheets
- Generated presentations
- Generated PDFs
- Export packages
- Temporary processing objects

Do NOT store large binary files directly inside PostgreSQL unless a future explicit architecture decision requires it.

PostgreSQL stores metadata and authorization context.

---

## 5.2 Blob namespace

Blob paths MUST be generated by the backend.

Recommended structure:

```text
organizations/{organization_id}/
    workspaces/{workspace_id}/
        projects/{project_id}/
            files/{file_id}/
                original
                versions/{version_id}/...
            artifacts/{artifact_id}/
                versions/{version_id}/...
            temporary/{job_id}/...
```

The application MUST NOT allow clients to submit arbitrary blob paths.

---

# 6. Azure Managed Redis

Redis is not the source of truth.

Use Azure Managed Redis for:

- Short-lived cache
- Rate limiting
- Distributed locks
- Idempotency keys
- Job/worker coordination
- Temporary execution state
- Session-like ephemeral state
- Frequently accessed configuration cache

Do NOT store authoritative:

- Users
- Projects
- Messages
- Files
- Audit events
- Usage records

in Redis.

Redis data MUST be disposable.

If Redis is completely lost, Nexus should recover from PostgreSQL and durable storage.

---

# 7. Azure Key Vault

Secrets MUST be stored in Azure Key Vault or an equivalent managed secret system.

Examples:

- OpenAI API keys
- Anthropic API keys
- Azure OpenAI credentials
- OAuth client secrets
- Database credentials where required
- Signing secrets
- Encryption keys
- MCP credentials
- External integration secrets

Database records may contain:

```text
credential_ref
```

but MUST NOT contain plaintext secret values.

---

# 8. Canonical Domain Hierarchy

The primary ownership hierarchy is:

```text
User
  │
  └── Organization Membership
          │
          ▼
      Organization
          │
          └── Workspace
                  │
                  └── Project
                          │
                          ├── Conversation
                          │     └── Message
                          │
                          ├── File
                          │
                          ├── KnowledgeBase
                          │     └── Document
                          │            └── DocumentChunk
                          │
                          ├── Agent
                          │     ├── Tool bindings
                          │     └── MCP bindings
                          │
                          ├── Workflow
                          │
                          ├── Artifact
                          │
                          ├── AuditEvent
                          │
                          └── UsageRecord
```

This hierarchy is fundamental to authorization.

---

# 9. Scope Model

Every resource has a scope.

Allowed scopes:

```text
GLOBAL
ORGANIZATION
WORKSPACE
PROJECT
USER
```

The implementation SHOULD represent ownership explicitly rather than relying entirely on parent traversal.

For project-owned data, store:

```text
organization_id
workspace_id
project_id
```

when practical.

This is intentional denormalization for:

- Security
- Query performance
- RLS
- Integrity checking
- Easier auditing
- Safer background processing

---

# 10. Entity: User

## Purpose

Represents a human identity.

## Required fields

```text
id BIGINT PRIMARY KEY
public_id UUID NOT NULL UNIQUE
email
display_name
avatar_url nullable
status
email_verified_at nullable
last_login_at nullable
created_at
updated_at
deleted_at nullable
```

## Rules

- Email uniqueness should be defined according to identity architecture.
- A user can belong to multiple organizations.
- A user is NOT a tenant.
- Organization roles MUST NOT be stored as a single field on User.
- Use membership tables.

## Relationships

```text
User
 ├── OrganizationMembership[]
 ├── WorkspaceMembership[]
 ├── ProjectMembership[]
 ├── created_projects
 ├── created_conversations
 ├── created_files
 ├── created_artifacts
 └── audit_events
```

---

# 11. Supporting Entity: OrganizationMembership

Although not in the minimum requested entity list, this entity is REQUIRED for correct multi-tenancy.

## Purpose

Associates a user with an organization.

## Fields

```text
id
organization_id
user_id
role_id
status
invited_by
joined_at
created_at
updated_at
```

## Constraints

```text
UNIQUE(organization_id, user_id)
```

Organization membership is required before a user can access organization-owned resources.

---

# 12. Supporting Entity: WorkspaceMembership

Associates a user with a workspace.

```text
id
workspace_id
user_id
role_id
status
created_at
updated_at
```

Constraint:

```text
UNIQUE(workspace_id, user_id)
```

---

# 13. Supporting Entity: ProjectMembership

Associates a user with a project.

```text
id
project_id
user_id
role_id
status
created_at
updated_at
```

Constraint:

```text
UNIQUE(project_id, user_id)
```

Project membership is the preferred mechanism for project-level access.

---

# 14. Entity: Organization

## Purpose

Primary tenant boundary.

## Fields

```text
id BIGINT PRIMARY KEY
public_id UUID NOT NULL UNIQUE
name
slug
status
settings_json JSONB
created_at
updated_at
deleted_at
```

## Rules

An organization owns tenant-level configuration and resources.

All organization-owned data MUST be attributable to exactly one organization.

## Relationships

```text
Organization
 ├── Memberships
 ├── Workspaces
 ├── Projects
 ├── Providers
 ├── Models
 ├── Tools
 ├── MCPServers
 ├── AuditEvents
 └── UsageRecords
```

---

# 15. Entity: Workspace

## Purpose

Organizational subdivision.

## Fields

```text
id
organization_id
name
slug
description
settings_json
created_at
updated_at
deleted_at
```

## Rules

A workspace belongs to exactly one organization.

Constraint:

```text
UNIQUE(organization_id, slug)
```

A workspace MUST NOT reference projects belonging to another organization.

---

# 16. Entity: Project

## Purpose

Primary AI application and execution isolation boundary.

## Fields

```text
id
organization_id
workspace_id
name
slug
description
status
settings_json
created_by
created_at
updated_at
deleted_at
```

## Rules

Project must satisfy:

```text
project.organization_id == workspace.organization_id
```

Project is the default scope for:

- Conversations
- Messages
- Files
- Documents
- Knowledge bases
- Agents
- Workflows
- Artifacts
- Project tools
- Project MCP servers

## Constraint

Prefer:

```text
UNIQUE(workspace_id, slug)
```

---

# 17. Entity: Conversation

## Purpose

Represents an AI interaction/session.

## Fields

```text
id
organization_id
workspace_id
project_id
created_by
title
status
metadata_json
created_at
updated_at
deleted_at
```

## Rules

A conversation belongs to exactly one project.

A conversation MUST NOT span projects.

---

# 18. Entity: Message

## Purpose

Represents an individual conversational message.

## Fields

```text
id
organization_id
workspace_id
project_id
conversation_id
parent_message_id nullable
role
content
content_json JSONB nullable
sequence_number
model_id nullable
provider_id nullable
agent_id nullable
input_tokens nullable
output_tokens nullable
cached_tokens nullable
latency_ms nullable
status
metadata_json
created_at
```

## Roles

Initial roles:

```text
system
developer
user
assistant
tool
```

## Message content

Support structured multimodal blocks.

Example:

```json
{
  "blocks": [
    {
      "type": "text",
      "text": "Analyze this file."
    },
    {
      "type": "file",
      "file_id": "..."
    }
  ]
}
```

## Ordering

Use:

```text
sequence_number
```

for deterministic conversation ordering.

Recommended constraint:

```text
UNIQUE(conversation_id, sequence_number)
```

---

# 19. Entity: File

## Purpose

Represents file metadata and the relationship between Nexus and Azure Blob Storage.

## Fields

```text
id
organization_id
workspace_id
project_id
owner_user_id
conversation_id nullable
storage_container
storage_key
original_filename
mime_type
size_bytes
checksum
storage_provider
status
metadata_json
created_at
updated_at
deleted_at
```

## Storage

Binary content lives in Azure Blob Storage.

PostgreSQL stores:

- ownership
- authorization scope
- metadata
- checksum
- storage key
- lifecycle state

## Security

Blob access MUST be mediated through Nexus authorization.

Use short-lived authorized access mechanisms such as SAS where appropriate.

---

# 20. Entity: Document

## Purpose

Represents a logical parsed/indexable document.

A Document is usually derived from a File.

## Fields

```text
id
organization_id
workspace_id
project_id
file_id
knowledge_base_id
title
source_type
source_uri nullable
mime_type
version
status
metadata_json
created_at
updated_at
deleted_at
```

## Lifecycle

```text
uploaded
queued
processing
parsed
chunking
embedding
indexed
ready
failed
deleted
```

---

# 21. Entity: DocumentChunk

## Purpose

Represents a searchable segment of a Document.

## Fields

```text
id
organization_id
workspace_id
project_id
document_id
chunk_index
content
token_count
embedding
embedding_model_id
embedding_dimension
metadata_json
created_at
```

## Rules

A chunk belongs to exactly one document.

Chunk index should be unique within a document:

```text
UNIQUE(document_id, chunk_index)
```

## Vector search

Use pgvector.

Every retrieval query MUST enforce authorization scope.

Recommended conceptual filter:

```sql
WHERE organization_id = :organization_id
  AND project_id = :project_id
  AND knowledge_base_id = :knowledge_base_id
```

The exact SQL may differ based on schema normalization.

---

# 22. Entity: KnowledgeBase

## Purpose

Project-scoped collection of documents used for retrieval/RAG.

## Fields

```text
id
organization_id
workspace_id
project_id
name
description
embedding_model_id
retrieval_config_json
status
created_by
created_at
updated_at
deleted_at
```

## Rules

Default visibility is project-local.

Cross-project knowledge sharing requires explicit authorization and should not be achieved by simply querying another project's records.

---

# 23. Entity: Provider

## Purpose

Represents an AI/inference provider.

Examples:

```text
Azure OpenAI
OpenAI
Anthropic
Google
self-hosted inference
other compatible provider
```

## Fields

```text
id
organization_id
name
provider_type
base_url
credential_ref
status
configuration_json
created_at
updated_at
deleted_at
```

## Security

Never store API secrets directly in this table.

Use:

```text
credential_ref → Azure Key Vault
```

---

# 24. Entity: Model

## Purpose

Represents a selectable model...