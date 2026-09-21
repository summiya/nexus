# Nexus AI — Data Model & Persistence Architecture

**Document:** `docs/06-data-model.md`  
**Document Type:** Canonical Technical Specification  
**Document Status:** Implementation Baseline  
**Version:** 1.0  
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

AI coding agents MUST follow the architecture, ownership rules, relationship rules, isolation boundaries, storage rules, and persistence decisions defined in this document.

AI coding agents MUST NOT introduce a new database, storage system, vector database, ORM, or persistence technology without an explicit architecture decision.

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

The implementation MUST NOT introduce a different primary database, object-storage model, or tenant hierarchy without an explicit architecture decision.

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
id UUID PRIMARY KEY
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
id UUID PRIMARY KEY
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

## Implemented Generation concurrency and request deduplication

The current Conversation implementation persists each model attempt in a
`generations` row. Its status values are stored as lowercase strings, including
`running`.

PostgreSQL is authoritative for these implemented invariants:

```text
uq_generations_one_running_per_conversation
    UNIQUE (organization_id, conversation_id)
    WHERE status = 'running'

uq_generations_conversation_idempotency_key
    UNIQUE (organization_id, conversation_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL
```

The first index permits at most one active generation per Conversation. The
second provides optional at-most-once message submission when a client sends a
UUID `Idempotency-Key`. It does not provide SSE replay or resumption. Because
the idempotency identity includes the Conversation, the same key may be reused
for a different Conversation.

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

Represents a selectable model exposed through a Provider.

## Fields

```text
id
organization_id
provider_id
name
model_identifier
model_type
context_window
input_price
output_price
capabilities_json
status
created_at
updated_at
deleted_at
```

## Types

```text
chat
reasoning
embedding
vision
audio
image
reranker
```

## Relationships

```text
Provider 1 ─── N Model
Model 1 ─── N Message
Model 1 ─── N UsageRecord
Model 1 ─── N KnowledgeBase
Model 1 ─── N Agent
```

A Model record represents Nexus configuration, not the actual model weights.

---

# 25. Entity: Agent

## Purpose

Represents an autonomous or semi-autonomous AI worker.

## Fields

```text
id
organization_id
workspace_id
project_id
name
description
system_prompt
model_id
configuration_json
status
version
created_by
created_at
updated_at
deleted_at
```

## Configuration may include

```text
temperature
max_tokens
reasoning configuration
memory configuration
tool policy
MCP policy
retrieval policy
approval policy
timeout
retry policy
```

## Relationships

```text
Project 1 ─── N Agent
Agent N ─── 1 Model
Agent N ─── N Tool
Agent N ─── N MCPServer
Agent N ─── N Workflow
```

---

# 26. Entity: Tool

## Purpose

Represents an executable capability.

Examples:

```text
web search
file search
database query
code execution
HTTP request
internal API
calculator
document generation
```

## Fields

```text
id
organization_id
workspace_id nullable
project_id nullable
name
description
tool_type
configuration_json
permission_policy_json
status
created_by
created_at
updated_at
deleted_at
```

## Security

Tool configuration must define where appropriate:

- input schema
- output schema
- timeout
- network restrictions
- rate limits
- maximum output
- approval requirement
- allowed agents
- allowed workflows
- allowed projects
- secret references

Tools are privileged execution resources.

---

# 27. Entity: MCPServer

## Purpose

Represents an MCP-compatible server.

## Fields

```text
id
organization_id
workspace_id nullable
project_id nullable
name
description
server_type
endpoint
credential_ref
configuration_json
permission_policy_json
status
created_by
created_at
updated_at
deleted_at
```

## Security

MCP servers MUST be explicitly authorized.

MCP access is never implicitly trusted.

Each invocation should record:

- actor
- project
- agent/workflow
- MCP server
- tool name
- request
- result status
- latency
- errors
- relevant metadata

Sensitive request/response content must be redacted according to the security policy.

---

# 28. Entity: Workflow

## Purpose

Represents an executable orchestration definition.

## Fields

```text
id
organization_id
workspace_id
project_id
name
description
definition_json
version
status
created_by
created_at
updated_at
deleted_at
```

## Definition

May contain:

```text
trigger
nodes
edges
conditions
agent calls
model calls
tool calls
MCP calls
human approval steps
retrieval
artifact generation
retry policies
timeouts
failure handling
```

## Versioning

Workflow definitions should become immutable after execution.

Preferred:

```text
Workflow
 ├── Version 1
 ├── Version 2
 └── Version 3
```

A workflow execution MUST reference the exact version used.

---

# 29. Entity: Artifact

## Purpose

Represents generated output.

Examples:

```text
PDF
DOCX
XLSX
PPTX
CSV
JSON
image
code package
report
```

## Fields

```text
id
organization_id
workspace_id
project_id
conversation_id nullable
workflow_id nullable
created_by
artifact_type
name
storage_key
mime_type
size_bytes
checksum
version
status
metadata_json
created_at
updated_at
deleted_at
```

## Storage

Binary artifact content lives in Azure Blob Storage.

PostgreSQL stores metadata and ownership.

---

# 30. Entity: AuditEvent

## Purpose

Immutable security and business audit record.

## Fields

```text
id
organization_id
workspace_id nullable
project_id nullable
actor_user_id nullable
actor_type
action
resource_type
resource_id
request_id
ip_address nullable
user_agent nullable
result
reason nullable
metadata_json
created_at
```

## Example actions

```text
authentication.succeeded
authentication.failed
authorization.denied
organization.created
member.invited
member.role_changed
project.created
project.deleted
file.uploaded
file.downloaded
document.ingested
knowledge_base.queried
provider.created
provider.updated
secret.accessed
agent.created
agent.updated
tool.permission_changed
mcp.invoked
workflow.executed
artifact.created
data.exported
```

## Rules

Audit events are append-only.

Normal application code MUST NOT update or delete audit history.

Failed security operations should also be auditable.

---

# 31. Entity: UsageRecord

## Purpose

Tracks consumption, operational usage, and estimated cost.

## Fields

```text
id
organization_id
workspace_id nullable
project_id nullable
user_id nullable
conversation_id nullable
workflow_id nullable
agent_id nullable
provider_id nullable
model_id nullable
usage_type
input_tokens nullable
output_tokens nullable
cached_tokens nullable
requests nullable
duration_ms nullable
storage_bytes nullable
estimated_cost nullable
currency nullable
metadata_json
created_at
```

## Usage types

```text
llm
embedding
image
audio
tool
mcp
storage
compute
workflow
```

Usage records are append-only.

Cost values are snapshots, not dynamically recalculated historical invoices.

---

# 32. Entity Relationship Map

```text
User
 │
 ├──< OrganizationMembership >── Organization
 │                                  │
 │                                  ├──< Workspace
 │                                  │       │
 │                                  │       └──< Project
 │                                  │               │
 │                                  │               ├──< Conversation
 │                                  │               │       └──< Message
 │                                  │               │
 │                                  │               ├──< File
 │                                  │               │
 │                                  │               ├──< KnowledgeBase
 │                                  │               │       └──< Document
 │                                  │               │               └──< DocumentChunk
 │                                  │               │
 │                                  │               ├──< Agent
 │                                  │               │       ├──> Model
 │                                  │               │       ├──< ToolBinding
 │                                  │               │       └──< MCPBinding
 │                                  │               │
 │                                  │               ├──< Workflow
 │                                  │               │
 │                                  │               ├──< Artifact
 │                                  │               ├──< AuditEvent
 │                                  │               └──< UsageRecord
 │                                  │
 │                                  ├──< Provider
 │                                  │       └──< Model
 │                                  │
 │                                  ├──< Tool
 │                                  └──< MCPServer
```

---

# 33. Ownership Matrix

| Entity | Scope | Organization ID | Project ID | Durable Store |
|---|---|---:|---:|---|
| User | Global | No | No | PostgreSQL |
| Organization | Organization | Yes | No | PostgreSQL |
| Workspace | Organization | Yes | No | PostgreSQL |
| Project | Project | Yes | Yes | PostgreSQL |
| Conversation | Project | Yes | Yes | PostgreSQL |
| Message | Project | Yes | Yes | PostgreSQL |
| File | Project | Yes | Yes | PostgreSQL + Blob |
| Document | Project | Yes | Yes | PostgreSQL |
| DocumentChunk | Project | Yes | Yes | PostgreSQL + pgvector |
| KnowledgeBase | Project | Yes | Yes | PostgreSQL |
| Provider | Organization | Yes | Optional | PostgreSQL |
| Model | Organization | Yes | Optional | PostgreSQL |
| Agent | Project | Yes | Yes | PostgreSQL |
| Tool | Organization/Project | Yes | Optional | PostgreSQL |
| MCPServer | Organization/Project | Yes | Optional | PostgreSQL |
| Workflow | Project | Yes | Yes | PostgreSQL |
| Artifact | Project | Yes | Yes | PostgreSQL + Blob |
| AuditEvent | Organization | Yes | Optional | PostgreSQL |
| UsageRecord | Organization | Yes | Optional | PostgreSQL |

---

# 34. Tenant Isolation Rules

Organization is the hard tenant boundary.

For every organization-owned request:

```text
authenticated user
      ↓
organization membership
      ↓
organization authorization
      ↓
resource authorization
```

Never trust:

```text
organization_id
```

sent by the client.

Resolve the authorized organization from authentication/session/context.

---

# 35. Project Isolation Rules

Project isolation is independent from organization membership.

A user belonging to Organization A does NOT automatically gain access to every project in Organization A.

Project access requires appropriate permission.

The authorization hierarchy is:

```text
User
 ↓
Organization membership
 ↓
Workspace membership/permission
 ↓
Project membership/permission
 ↓
Resource permission
 ↓
Tool/MCP permission
 ↓
Execution
```

---

# 36. Cross-Tenant Protection

A query like:

```sql
SELECT *
FROM projects
WHERE id = :project_id;
```

is insufficient.

Use:

```sql
SELECT *
FROM projects
WHERE id = :project_id
  AND organization_id = :organization_id;
```

For project resources:

```sql
SELECT *
FROM messages
WHERE id = :message_id
  AND organization_id = :organization_id
  AND project_id = :project_id;
```

Repositories should receive a validated security context.

Example conceptual object:

```text
SecurityContext
├── user_id
├── organization_id
├── workspace_id
├── project_id
└── permissions
```

---

# 37. Database Integrity

Use foreign keys wherever possible.

Important invariants:

```text
Workspace.organization_id
    → Organization.id

Project.workspace_id
    → Workspace.id

Project.organization_id
    → Organization.id

Conversation.project_id
    → Project.id

Message.conversation_id
    → Conversation.id

Message.project_id
    → Project.id

Document.file_id
    → File.id

Document.knowledge_base_id
    → KnowledgeBase.id

DocumentChunk.document_id
    → Document.id

Agent.project_id
    → Project.id

Workflow.project_id
    → Project.id
```

Where supported and practical, use composite foreign keys to enforce matching tenant scope.

---

# 38. Composite Scope Integrity

For project-owned records, a strong pattern is:

```text
(parent_id, organization_id)
```

referencing:

```text
parent(id, organization_id)
```

This prevents a child record from referencing a parent belonging to another organization.

For example:

```text
documents
    project_id
    organization_id

projects
    id
    organization_id
```

should be validated so:

```text
documents.project_id
    belongs to
documents.organization_id
```

This is defense in depth.

---

# 39. Row-Level Security

PostgreSQL Row-Level Security SHOULD be used for sensitive tenant-owned tables.

Potential RLS-protected tables:

```text
workspaces
projects
conversations
messages
files
documents
document_chunks
knowledge_bases
agents
tools
mcp_servers
workflows
artifacts
audit_events
usage_records
```

RLS should complement—not replace—application authorization.

The service layer should still enforce permissions.

---

# 40. Vector Security

Vector search is a high-risk data-leakage surface.

Never perform:

```text
embedding → global similarity search → permission filtering
```

Instead:

```text
security context
 ↓
authorized organization
 ↓
authorized project
 ↓
authorized knowledge base
 ↓
vector similarity
 ↓
top K authorized chunks
```

A chunk from another organization must never enter the model context.

A chunk from another project must not enter the model context unless explicit sharing has been implemented and authorized.

---

# 41. RAG Data Flow

Canonical RAG ingestion:

```text
User uploads File
        ↓
FastAPI authorization
        ↓
File metadata → PostgreSQL
        ↓
Binary → Azure Blob Storage
        ↓
Background ingestion job
        ↓
Document created
        ↓
Text extraction
        ↓
Chunking
        ↓
DocumentChunk records
        ↓
Embedding generation
        ↓
pgvector embedding stored
        ↓
KnowledgeBase marked READY
```

Canonical retrieval:

```text
User query
    ↓
Project authorization
    ↓
Query embedding
    ↓
PostgreSQL/pgvector
    ↓
organization_id filter
    ↓
project_id filter
    ↓
knowledge_base filter
    ↓
similarity ranking
    ↓
authorized chunks
    ↓
LLM context
```

---

# 42. File Data Flow

```text
Client
  ↓
FastAPI
  ↓
Authorize project
  ↓
Create File metadata
  ↓
Generate secure storage key
  ↓
Azure Blob Storage
  ↓
Return file reference
```

The client MUST NOT choose:

- organization path
- project path
- storage key
- container name

The backend derives these values from authorized context.

---

# 43. Artifact Data Flow

```text
Agent / Workflow
      ↓
Generate artifact
      ↓
Validate project ownership
      ↓
Write Blob
      ↓
Create Artifact metadata
      ↓
Audit event
      ↓
Usage record
      ↓
Authorized download
```

---

# 44. Model and Provider Architecture

Nexus must use a provider abstraction.

Conceptually:

```text
                    Nexus Model Gateway
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
        Azure OpenAI      OpenAI       Anthropic
             │              │              │
             └──────────────┼──────────────┘
                            ▼
                       Nexus Model
                         Registry
```

The Agent should reference a Nexus `Model`.

The Agent should NOT hard-code provider-specific credentials.

Example:

```text
Agent
  ↓
Model
  ↓
Provider
  ↓
Credential Reference
  ↓
Azure Key Vault
```

This allows Nexus to route different agents to different providers.

---

# 45. Agent Resource Model

An Agent should be considered a policy-controlled execution identity.

An Agent may have:

```text
Model
Tools
MCP servers
Knowledge bases
Workflow permissions
Memory configuration
Approval requirements
```

Access must be explicit.

Do NOT implement:

```text
agent can use every tool in project
```

Prefer:

```text
Agent
  ├── ToolBinding A
  ├── ToolBinding B
  └── MCPBinding C
```

---

# 46. Tool Binding

Recommended supporting table:

```text
agent_tools

id
organization_id
project_id
agent_id
tool_id
permission
configuration_json
created_at
```

Possible permissions:

```text
execute
read
write
admin
```

The actual permission vocabulary should be defined by the authorization system.

---

# 47. MCP Binding

Recommended:

```text
agent_mcp_servers

id
organization_id
project_id
agent_id
mcp_server_id
permission_policy_json
created_at
```

The binding determines which MCP servers an agent can use.

---

# 48. Workflow Execution Model

The initial domain model defines the Workflow itself.

Future runtime entities should include:

```text
WorkflowRun
WorkflowRunStep
ToolInvocation
MCPInvocation
AgentExecution
```

These should reference the exact:

```text
workflow_id
workflow_version
project_id
organization_id
```

A workflow run MUST remain reproducible.

---

# 49. Versioning

Version immutable configuration where historical reproducibility matters.

Entities likely requiring versions:

```text
Agent
Workflow
Tool
MCPServer
KnowledgeBase configuration
Provider configuration
```

Recommended approach:

```text
logical resource
      │
      ├── version 1
      ├── version 2
      └── version 3
```

Do not modify historical configuration in a way that changes the meaning of a previous execution.

---

# 50. Audit Requirements

Every security-sensitive mutation should produce an AuditEvent.

Examples:

```text
login
failed login
role change
project creation
project deletion
file access
provider configuration
secret reference change
agent change
tool permission change
MCP permission change
workflow execution
data export
authorization denial
```

Audit events should contain:

```text
who
what
when
where
which resource
which project
which organization
request_id
result
reason
```

---

# 51. Usage Architecture

Usage should be generated close to actual execution.

Example LLM request:

```text
Agent
 ↓
Model Gateway
 ↓
Provider
 ↓
LLM
 ↓
response
 ↓
UsageRecord
```

Capture:

```text
provider
model
project
agent
user
conversation
tokens
duration
estimated cost
```

Usage records should not be overwritten.

---

# 52. Database Indexing

At minimum index:

```text
organization_id
workspace_id
project_id
created_at
updated_at
status
```

Important composite indexes:

```text
(project_id, created_at)
(project_id, updated_at)
(organization_id, created_at)
(organization_id, status)
(conversation_id, sequence_number)
(document_id, chunk_index)
(knowledge_base_id, document_id)
(agent_id, created_at)
(workflow_id, created_at)
```

Indexes must be driven by actual query patterns after implementation.

Do not create hundreds of speculative indexes.

---

# 53. Uniqueness Rules

Recommended:

```text
Organization:
    UNIQUE(slug)

Workspace:
    UNIQUE(organization_id, slug)

Project:
    UNIQUE(workspace_id, slug)

KnowledgeBase:
    UNIQUE(project_id, name)

Agent:
    UNIQUE(project_id, name)

Tool:
    UNIQUE(project_id, name)

MCPServer:
    UNIQUE(project_id, name)

Workflow:
    UNIQUE(project_id, name)

Conversation:
    no global name uniqueness

Message:
    UNIQUE(conversation_id, sequence_number)

DocumentChunk:
    UNIQUE(document_id, chunk_index)
```

Global uniqueness should only be used where product semantics require it.

---

# 54. Soft Deletion

Use:

```text
deleted_at
```

for resources that require recovery or auditability.

Soft deletion should generally apply to:

```text
Organization
Workspace
Project
Conversation
File
Document
KnowledgeBase
Agent
Tool
MCPServer
Workflow
Artifact
Provider
Model
```

AuditEvent and UsageRecord should not be normally soft-deleted by the application.

They are append-only records.

---

# 55. Deletion Behavior

Deleting a Project must NOT blindly cascade everything.

Preferred lifecycle:

```text
Project
 ↓
disable new execution
 ↓
disable agents/workflows
 ↓
archive conversations
 ↓
apply file retention policy
 ↓
apply document retention policy
 ↓
retain required audit events
 ↓
retain required usage records
 ↓
eventual physical cleanup
```

Physical cleanup should be performed asynchronously according to retention policy.

---

# 56. Transaction Boundaries

## Create Project

One transaction should cover:

```text
project
initial configuration
membership initialization
audit event
```

## Create Agent

One transaction should cover:

```text
agent
model authorization
initial bindings
audit event
```

## Upload File

Metadata creation and storage operations require an explicit consistency strategy.

At minimum:

```text
authorize
create file record
upload blob
update file status
```

Failures must produce a recoverable state.

## Workflow Execution

The execution should capture:

```text
workflow version
project
organization
initiating user
execution ID
```

before long-running work begins.

---

# 57. Background Jobs

Long-running operations should not block FastAPI requests.

Examples:

```text
document ingestion
text extraction
chunking
embedding
artifact generation
large exports
workflow execution
scheduled tasks
cleanup
```

Background jobs MUST carry security context:

```text
organization_id
workspace_id
project_id
user_id
resource_id
```

A worker MUST NOT execute a job using only a raw resource ID without validating ownership.

---

# 58. Idempotency

Operations that can be retried should support idempotency.

Examples:

```text
file ingestion
workflow execution
artifact generation
external API calls
MCP calls
billing/usage recording
```

Use an idempotency key or deterministic job identity where appropriate.

Redis may temporarily store idempotency state, but durable business results belong in PostgreSQL.

---

# 59. Concurrency

Use optimistic concurrency where configuration can be edited concurrently.

Potential fields:

```text
version
updated_at
```

Especially:

```text
Agent
Workflow
Tool
MCPServer
Provider
KnowledgeBase
```

Avoid silently overwriting a newer configuration.

---

# 60. Control Plane vs Data Plane

Nexus should conceptually separate configuration from execution.

## Control plane

```text
Organization
Workspace
Project
Provider
Model
Agent
Tool
MCPServer
Workflow
KnowledgeBase configuration
Permissions
```

## Data plane

```text
Conversation
Message
File
Document
DocumentChunk
Artifact
WorkflowRun
ToolInvocation
MCPInvocation
UsageRecord
```

## Security plane

```text
AuditEvent
Authentication
Authorization
Secret references
Policy enforcement
```

This separation makes the future execution engine easier to evolve.

---

# 61. What Each Database/Service Is For

This section is especially important for AI implementation agents.

## PostgreSQL

**Use PostgreSQL for authoritative structured data.**

Examples:

```text
users
organizations
memberships
workspaces
projects
conversations
messages
files metadata
documents
document chunks
knowledge bases
providers
models
agents
tools
MCP servers
workflows
artifacts metadata
audit events
usage records
permissions
versions
```

## pgvector

**Use pgvector for semantic/vector retrieval.**

Examples:

```text
DocumentChunk.embedding
```

Do not use it as a general-purpose database.

## Azure Blob Storage

**Use Blob Storage for large binary objects.**

Examples:

```text
uploaded PDFs
DOCX
images
CSV
generated XLSX
generated PPTX
generated PDF
large exports
```

## Azure Managed Redis

**Use Redis for ephemeral/high-speed infrastructure concerns.**

Examples:

```text
cache
rate limiting
distributed locks
idempotency
temporary state
job coordination
```

## Azure Key Vault

**Use Key Vault for secrets.**

Examples:

```text
LLM API keys
OAuth secrets
MCP credentials
signing keys
encryption keys
```

## LLM providers

**Use providers for inference.**

Examples:

```text
Azure OpenAI
OpenAI
Anthropic
other supported providers
```

Providers are not Nexus persistence systems.

---

# 62. What NOT to Use Initially

Do not add these unless a later architecture decision requires them:

```text
MongoDB
MySQL
SQLite in production
Pinecone
Weaviate
Milvus
Qdrant
Chroma
Elasticsearch
Cassandra
DynamoDB
Neo4j
```

This is not because these technologies are bad.

The reason is architectural simplicity.

The initial Nexus stack should avoid unnecessary distributed persistence.

---

# 63. Recommended Azure Architecture

```text
                         ┌──────────────────────┐
                         │       Users          │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │      Next.js         │
                         │       Frontend       │
                         └──────────┬───────────┘
                                    │ HTTPS
                                    ▼
                         ┌──────────────────────┐
                         │    FastAPI API       │
                         │       Backend        │
                         └──────────┬───────────┘
                                    │
          ┌─────────────────────────┼──────────────────────────┐
          │                         │                          │
          ▼                         ▼                          ▼
 ┌─────────────────┐      ┌─────────────────┐       ┌─────────────────┐
 │ Azure PostgreSQL│      │ Azure Managed    │       │ Azure Blob      │
 │ + pgvector      │      │ Redis            │       │ Storage         │
 └────────┬────────┘      └─────────────────┘       └─────────────────┘
          │
          │
          ▼
 ┌─────────────────┐
 │ Nexus Domain    │
 │ Data            │
 └─────────────────┘

                         ┌──────────────────────┐
                         │    Azure Key Vault   │
                         └──────────┬───────────┘
                                    │
                                    ▼
                            Provider Credentials

                         ┌──────────────────────┐
                         │    Model Providers   │
                         ├──────────────────────┤
                         │ Azure OpenAI         │
                         │ OpenAI               │
                         │ Anthropic            │
                         │ Other providers      │
                         └──────────────────────┘
```

---

# 64. Local Development Equivalent

Local development should preserve the same conceptual architecture.

Recommended Docker Compose services:

```text
api
web
postgres
redis
worker
```

For local object storage, use an S3-compatible development service only if necessary for local parity, while keeping the production abstraction as:

```text
ObjectStorageService
```

Production implementation:

```text
AzureBlobStorageService
```

This prevents cloud-specific storage logic from spreading throughout the application.

---

# 65. Storage Abstraction

Application code SHOULD NOT directly call Azure Blob APIs throughout domain services.

Use an abstraction:

```text
ObjectStorageService
```

Conceptual interface:

```text
upload()
download()
delete()
exists()
generate_download_url()
generate_upload_url()
```

Azure implementation:

```text
AzureBlobStorageService
```

This gives Nexus:

- Testability
- Local development flexibility
- Future cloud portability
- Centralized security
- Centralized path generation

---

# 66. Repository Architecture

Recommended backend layering:

```text
API
 ↓
Service
 ↓
Repository
 ↓
PostgreSQL
```

For files:

```text
API
 ↓
Service
 ├── Repository → PostgreSQL
 └── ObjectStorageService → Azure Blob
```

For AI:

```text
Agent Service
 ↓
Model Gateway
 ↓
Provider Adapter
 ↓
Azure OpenAI / OpenAI / Anthropic
```

The domain model must not depend directly on a provider SDK.

---

# 67. SQLAlchemy Guidance

The Python backend should use SQLAlchemy ORM/Core as the database abstraction.

Recommended:

```text
apps/api/
    app/
        models/
        schemas/
        repositories/
        services/
        api/
        security/
        workers/
```

SQLAlchemy models should represent domain persistence.

Pydantic schemas should represent API input/output.

Do not expose SQLAlchemy ORM objects directly as public API contracts.

---

# 68. Alembic Migrations

All schema changes MUST use Alembic migrations.

Never make production schema changes manually.

Migration sequence should be:

```text
model change
 ↓
Alembic migration
 ↓
migration test
 ↓
upgrade
 ↓
application deployment
```

Destructive migrations should be staged carefully.

---

# 69. API Security Context

Every protected API request should resolve a security context similar to:

```text
SecurityContext
{
    user_id,
    organization_id,
    workspace_id?,
    project_id?,
    permissions,
    roles
}
```

Repositories should use the context to constrain queries.

AI agents must never be allowed to choose arbitrary:

```text
organization_id
project_id
user_id
```

for privileged operations.

---

# 70. AI Agent Data Access

AI agents operate under the Nexus security model.

An agent MUST NOT have database-wide access.

An agent should receive scoped capabilities:

```text
Agent
 ├── project
 ├── knowledge bases
 ├── tools
 ├── MCP servers
 └── allowed operations
```

If an agent needs data, it should use an authorized service/tool.

Do not give agents unrestricted PostgreSQL credentials.

---

# 71. Prompt Injection and Data Boundary

The data model must support the security principle that retrieved content is **data**, not authority.

For example:

```text
DocumentChunk content
```

must never be interpreted as permission to:

- Access another project
- Call arbitrary tools
- Read secrets
- Modify authorization
- Override system instructions

Authorization is determined by Nexus policy, not by text contained in:

- Documents
- Messages
- Files
- Tool results
- MCP results
- Web pages

---

# 72. Secret Isolation

Secret values MUST NOT be stored in:

```text
Message.content
DocumentChunk.content
Tool.configuration_json
MCPServer.configuration_json
Agent.configuration_json
AuditEvent.metadata_json
UsageRecord.metadata_json
```

If a resource needs a secret, store:

```text
credential_ref
```

and resolve the secret through Key Vault at execution time.

Secrets must never be inserted into model context unless an explicit, controlled integration requires it.

---

# 73. Audit vs Application Data

Do not use application tables as an audit log.

For example:

```text
project.updated
```

should create:

```text
Project update
+
AuditEvent
```

Do not infer security history only from:

```text
Project.updated_at
```

AuditEvent exists to answer:

```text
Who did what?
When?
To which resource?
From which request?
Was it allowed?
Did it succeed?
```

---

# 74. Data Retention

Retention policies should eventually be configurable at organization level.

Potential policies:

```text
conversation retention
file retention
artifact retention
audit retention
usage retention
document retention
workflow execution retention
```

Retention jobs must respect legal/compliance requirements.

Audit records may have longer retention than runtime data.

---

# 75. Backup and Recovery

PostgreSQL is the primary durable system and therefore requires:

- Automated backups
- Point-in-time recovery
- Backup encryption
- Restore testing

Azure Blob Storage requires:

- Appropriate redundancy
- Versioning where needed
- Lifecycle policies
- Recovery strategy

Redis does not replace either backup system.

---

# 76. Disaster Recovery Principle

If Redis disappears:

```text
Nexus continues from PostgreSQL + Blob Storage
```

If a worker disappears:

```text
jobs can be retried
```

If an API instance disappears:

```text
another API instance continues
```

If a single LLM provider fails:

```text
Model Gateway can route/fail over according to policy
```

The architecture should avoid making any ephemeral service a single source of truth.

---

# 77. Required Future Supporting Entities

The following are intentionally outside the initial requested list but should be expected as Nexus evolves:

```text
OrganizationMember
WorkspaceMember
ProjectMember

Role
Permission
RolePermission

AgentVersion
WorkflowVersion
WorkflowRun
WorkflowRunStep

ToolInvocation
MCPInvocation
AgentExecution

Secret
SecretVersion

FileVersion
ArtifactVersion

RetrievalQuery
RetrievalResult

APIKey
OAuthConnection
Webhook

Job
JobAttempt

PromptTemplate
Evaluation
EvaluationRun
Dataset
```

AI agents should NOT create these entities prematurely unless the related feature is being implemented.

---

# 78. Initial Implementation Priority

## Phase 1 — Foundation

Implement:

```text
User
Organization
OrganizationMembership
Workspace
WorkspaceMembership
Project
ProjectMembership
```

## Phase 2 — Conversation

Implement:

```text
Conversation
Message
```

## Phase 3 — Files and RAG

Implement:

```text
File
KnowledgeBase
Document
DocumentChunk
pgvector
Azure Blob Storage
```

## Phase 4 — AI Configuration

Implement:

```text
Provider
Model
Agent
Tool
MCPServer
```

## Phase 5 — Orchestration

Implement:

```text
Workflow
Artifact
```

## Phase 6 — Observability

Implement:

```text
AuditEvent
UsageRecord
```

---

# 79. Canonical Rules for AI Coding Agents

AI coding agents MUST follow these rules:

1. PostgreSQL is the authoritative Nexus database.
2. pgvector runs inside PostgreSQL.
3. Azure Blob Storage stores large files and artifacts.
4. Azure Managed Redis stores only ephemeral/cache/coordination state.
5. Azure Key Vault stores secrets.
6. Organization is the hard tenant boundary.
7. Project is the primary AI data/execution isolation boundary.
8. Project-owned records should carry organization and project scope.
9. Never trust tenant/project IDs supplied by clients.
10. Authorization must happen before data retrieval.
11. Vector retrieval must be authorization-filtered.
12. Agents must not receive unrestricted database access.
13. Tools and MCP servers require explicit permission bindings.
14. Secrets must never be stored in ordinary domain JSON.
15. AuditEvent is append-only.
16. UsageRecord is append-only.
17. Workflow executions must reference immutable versions.
18. Files are metadata in PostgreSQL and bytes in Blob Storage.
19. Artifacts are metadata in PostgreSQL and bytes in Blob Storage.
20. Background jobs must carry tenant/project security context.
21. All schema changes require Alembic migrations.
22. Domain services must not depend directly on cloud/provider SDKs when an abstraction is appropriate.
23. Do not introduce additional databases without an architecture decision.
24. Cross-project sharing must be explicit, permissioned, auditable, and revocable.
25. Retrieved text is untrusted data and never an authorization source.

---

# 80. Final Architecture Decision

The initial Nexus persistence architecture is:

```text
PRIMARY SYSTEM OF RECORD
    Azure Database for PostgreSQL
              │
              └── pgvector
                   └── embeddings / RAG

BINARY STORAGE
    Azure Blob Storage
              ├── user files
              └── generated artifacts

EPHEMERAL INFRASTRUCTURE
    Azure Managed Redis
              ├── cache
              ├── rate limits
              ├── idempotency
              ├── locks
              └── worker coordination

SECRET MANAGEMENT
    Azure Key Vault
              └── provider/integration credentials

AI INFERENCE
    Nexus Model Gateway
              ├── Azure OpenAI
              ├── OpenAI
              ├── Anthropic
              └── future providers

APPLICATION
    Python + FastAPI
              │
              ├── repositories → PostgreSQL
              ├── object storage abstraction → Blob
              ├── cache/queue abstraction → Redis
              └── model gateway → AI providers
```

This architecture is the baseline for Nexus.

The goal is deliberately simple:

> **One authoritative relational database, one vector extension, one durable binary store, one ephemeral infrastructure store, one secret manager, and a provider-agnostic AI gateway.**

This gives Nexus a secure foundation for multi-tenancy, RAG, agents, tools, MCP, workflows, artifacts, usage, and future enterprise scale without prematurely introducing unnecessary infrastructure.
