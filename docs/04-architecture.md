# NEXUS Architecture

## 1. Purpose

This document defines the target architecture for NEXUS before implementation.

It establishes:

- System boundaries
- Architectural layers
- AI Platform module responsibilities
- RAG architecture
- Agent and workflow execution
- Tool and MCP integration
- Memory
- Dependency direction
- Synchronous and asynchronous execution
- Streaming and event architecture
- Security boundaries
- External service boundaries
- Data and artifact flows
- Failure handling
- Reliability, observability, usage, and cost concerns
- Architectural constraints

This document describes **what the system is and how its parts interact**. It intentionally avoids implementation-specific details such as package structures, concrete classes, database schemas, or provider SDK usage.

---

# 2. Architectural Overview

NEXUS follows a layered architecture:

```text
┌──────────────────────────────────────────────────────────┐
│            React + TypeScript Frontend                  │
│              UI / State / Streaming Client               │
└────────────────────────────┬─────────────────────────────┘
                             │ HTTP / SSE
                             ▼
┌──────────────────────────────────────────────────────────┐
│                       FastAPI                            │
│             API / Authentication / Transport             │
└────────────────────────────┬─────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────┐
│                  Application Layer                       │
│        Use Cases / Authorization / Orchestration          │
└────────────────────────────┬─────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────┐
│                 AI Platform / SDK                        │
│                                                          │
│ Core     Models     Retrieval     Agents     Tools       │
│ MCP      Memory     Workflows    Artifacts  Evaluation   │
│ Observability                                           │
└────────────────────────────┬─────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────┐
│                      Interfaces                           │
│ Model / Vector Store / Storage / Queue / Cache / MCP     │
│ Repository / External Service / Event / Observability    │
└────────────────────────────┬─────────────────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────┐
│                  Infrastructure                          │
│ DB / Cache / Object Storage / Vector DB / Queue          │
│ AI Providers / MCP Servers / External APIs / Monitoring  │
└──────────────────────────────────────────────────────────┘
```

The primary architectural principle is:

> **Dependencies flow toward stable abstractions, while infrastructure provides concrete implementations of those abstractions.**

The frontend and transport layers must not directly depend on databases, model providers, vector stores, or other infrastructure.

---

# 3. Architectural Layers

## 3.1 React + TypeScript Frontend

The React + TypeScript frontend is responsible for presentation and client-side interaction. The current implementation uses Vite for the frontend toolchain.

Responsibilities:

- Render application UI
- Manage client-side state
- Collect user input
- Display AI responses
- Consume streaming responses
- Display execution state and events
- Display artifacts and evaluation results
- Present errors and recovery actions
- Interact with backend APIs through defined contracts

The frontend must not:

- Call model providers directly
- Access databases directly
- Implement AI orchestration
- Implement RAG pipelines
- Implement provider-specific AI logic
- Contain infrastructure credentials

The frontend communicates with the backend through API and streaming contracts.

---

## 3.2 FastAPI

FastAPI is the transport and API boundary of the backend.

Responsibilities:

- HTTP API endpoints
- Request validation
- Response serialization
- Authentication boundary
- Authorization boundary
- Streaming endpoints
- API-level error translation
- Request context creation
- Delegating work to application use cases

FastAPI should remain thin.

API handlers must not contain:

- Business logic
- Agent orchestration
- Workflow logic
- Retrieval algorithms
- Model-provider logic
- Database implementation details
- Tool implementation details

FastAPI delegates application behavior to the Application Layer.

---

## 3.3 Application Layer

The Application Layer contains application-specific use cases and orchestration.

Examples:

```text
CreateAgent
RunAgent
ExecuteWorkflow
QueryKnowledge
IngestDocuments
UploadArtifact
EvaluateRun
GetExecution
CancelExecution
```

Responsibilities:

- Coordinate platform capabilities
- Execute application use cases
- Apply application-level authorization
- Coordinate transactions
- Translate API requests into platform operations
- Combine multiple platform modules when required
- Manage execution lifecycle at the application boundary

The Application Layer may depend on:

- AI Platform abstractions
- Interfaces
- Application/domain contracts

It must not depend directly on concrete infrastructure implementations.

Example:

```text
Application
    │
    ▼
Model Interface
    │
    ▼
Provider Adapter
    │
    ▼
External Model Provider
```

The Application Layer must not bypass the platform and call provider SDKs directly.

---

# 4. AI Platform / SDK

The AI Platform is the reusable technical foundation of NEXUS.

It provides the capabilities required to build AI applications without coupling applications to individual infrastructure providers.

The platform consists of:

```text
Core
Models
Retrieval
Agents
Tools
MCP
Memory
Workflows
Artifacts
Evaluation
Observability
```

The modules have clear responsibilities and communicate through stable contracts.

---

# 5. AI Platform Modules

## 5.1 Core

Core contains shared primitives and foundational contracts used across the platform.

Responsibilities:

- Common types
- Configuration primitives
- Errors
- Result types
- Execution context
- Identifiers
- Lifecycle primitives
- Shared protocols and interfaces
- Common platform-level utilities

Core must remain independent of higher-level platform modules.

Core must not depend on:

- Agents
- Workflows
- Retrieval
- Concrete providers
- Infrastructure

Core is the lowest-level platform module.

---

## 5.2 Models

Models provides provider-independent model abstractions.

Responsibilities:

- Model interfaces
- Chat/completion abstractions
- Structured output
- Tool-calling capabilities
- Model configuration
- Streaming
- Token and usage information
- Capability representation

Provider-specific behavior is isolated behind model interfaces.

Conceptually:

```text
Agent / Workflow
      │
      ▼
   Model API
      │
      ▼
 Model Interface
      │
 ┌────┴─────────────┐
 ▼                  ▼
Provider Adapter A  Provider Adapter B
```

The rest of the platform must not depend on a specific model provider.

---

## 5.3 Retrieval

Retrieval provides knowledge-access capabilities and contains the platform-level RAG architecture.

Retrieval is responsible for both ingestion and query-time retrieval.

Responsibilities:

- Document ingestion contracts
- Document parsing
- Content normalization
- Chunking
- Metadata extraction
- Embedding generation
- Indexing
- Vector search
- Keyword or lexical search where supported
- Hybrid retrieval where applicable
- Metadata filtering
- Reranking
- Retrieval results
- Context construction

Retrieval may depend on:

- Models
- Interfaces
- Core

Retrieval must not expose infrastructure-specific vector database APIs to consumers.

---

# 6. RAG Architecture

RAG is a first-class architectural capability of NEXUS rather than an incidental feature of Agents.

The conceptual pipeline is:

```text
                  INGESTION

Documents
    │
    ▼
Parsing / Extraction
    │
    ▼
Normalization
    │
    ▼
Chunking
    │
    ▼
Metadata
    │
    ▼
Embeddings
    │
    ▼
Indexing
    │
    ▼
Knowledge Store
```

At query time:

```text
                  QUERY

User / Agent Query
        │
        ▼
Query Processing
        │
        ▼
Retrieval
   ┌────┴─────┐
   │          │
Vector       Keyword
Search       Search
   │          │
   └────┬─────┘
        ▼
Candidate Results
        │
        ▼
Filtering / Reranking
        │
        ▼
Relevant Context
        │
        ▼
Agent / Model
        │
        ▼
Response
```

The RAG architecture separates:

1. **Knowledge ingestion**
2. **Knowledge indexing**
3. **Knowledge retrieval**
4. **Context construction**
5. **Generation**

RAG does not own model orchestration or agent reasoning.

Agents and workflows consume retrieval capabilities through the Retrieval contract.

---

## 6.1 Document Ingestion

Document ingestion is normally asynchronous because it can involve parsing, chunking, embedding, and indexing.

Conceptually:

```text
Upload
  │
  ▼
Artifact
  │
  ▼
Ingestion Execution
  │
  ▼
Parse
  │
  ▼
Chunk
  │
  ▼
Embed
  │
  ▼
Index
  │
  ▼
Ready for Retrieval
```

The ingestion system should preserve document and chunk metadata so that retrieved context can be traced back to its source.

---

## 6.2 Retrieval Query

A retrieval query should produce structured results containing sufficient metadata for downstream processing.

Conceptually:

```text
RetrievalResult
├── content
├── relevance information
├── source reference
├── document reference
├── metadata
└── retrieval context
```

The system should support access-control filtering before sensitive content reaches an agent or model.

---

## 6.3 RAG and Agents

Agents can use retrieval as one of their available capabilities.

```text
Agent
  │
  ▼
Reasoning
  │
  ├── Model
  ├── Tool
  ├── Memory
  ├── Retrieval ──► RAG
  └── MCP
```

Retrieval should not automatically be invoked for every model call. Agent or application policy determines when knowledge retrieval is required.

---

# 7. Agents

Agents provide autonomous or semi-autonomous AI execution.

Responsibilities:

- Agent definitions
- Instructions
- Model selection
- Tool selection
- Capability policies
- Agent execution
- Agent state
- Agent lifecycle
- Agent events
- Agent results

A conceptual agent loop is:

```text
Start
  │
  ▼
Load Context
  │
  ▼
Call Model
  │
  ▼
Interpret Model Decision
  │
  ├──────────► Final Response
  │
  ├──────────► Tool
  │
  ├──────────► Retrieval
  │
  ├──────────► Memory
  │
  └──────────► MCP
                 │
                 ▼
             Tool Result
                 │
                 ▼
             Call Model
```

Agents may coordinate:

- Models
- Tools
- Retrieval
- Memory
- MCP
- Observability

Agents should consume these capabilities through stable contracts.

---

# 8. Tools

Tools represent executable capabilities available to agents and workflows.

Responsibilities:

- Tool definitions
- Tool schemas
- Input validation
- Capability metadata
- Permission checks
- Execution
- Results
- Errors
- Timeouts and cancellation where applicable

Conceptual flow:

```text
Agent / Workflow
      │
      ▼
 Tool Registry
      │
      ▼
Authorization / Policy
      │
      ▼
 Input Validation
      │
      ▼
 Tool Executor
      │
 ┌────┴──────────────┐
 ▼                   ▼
Internal Tool      External Tool
```

Tools may represent:

- Internal application operations
- External APIs
- Database operations
- Computation
- File operations
- Other platform capabilities

Tool execution must be isolated from model reasoning.

---

# 9. MCP

MCP provides Model Context Protocol integration.

Responsibilities:

- MCP client capabilities
- MCP server integration
- Tool discovery
- Resource discovery
- Prompt discovery where applicable
- MCP transport handling
- Mapping MCP capabilities into NEXUS platform contracts
- MCP capability lifecycle

Conceptually:

```text
Agent
  │
  ▼
MCP Capability
  │
  ▼
MCP Client
  │
  ▼
MCP Server
  │
  ├── Tools
  ├── Resources
  └── Prompts
```

MCP-specific protocol concerns remain inside the MCP module.

Agents and workflows should consume MCP capabilities through platform-level contracts rather than implementing MCP protocol handling themselves.

MCP tools must be subject to the same authorization, validation, timeout, auditing, and failure policies as other tools.

---

# 10. Memory

Memory provides persistent contextual information associated with users, sessions, agents, conversations, or executions.

Responsibilities:

- Memory records
- Memory storage
- Memory retrieval
- Memory scopes
- Memory lifecycle
- Memory policies
- Memory relevance

Possible scopes include:

```text
User
Session
Conversation
Agent
Execution
Application
```

Memory is distinct from RAG.

### Memory

Represents information retained about interactions, entities, or prior executions.

### Retrieval / RAG

Provides access to indexed knowledge and source documents.

The distinction is:

```text
Memory
   → What the system remembers

RAG
   → What the system can retrieve from knowledge
```

Both may be provided as context to an Agent.

---

# 11. Workflows

Workflows provide deterministic multi-step orchestration.

Responsibilities:

- Workflow definitions
- Steps
- Dependencies
- Branching
- Parallel execution
- Execution state
- Scheduling
- Retries
- Timeouts
- Workflow events
- Results

Workflows may invoke:

```text
Agents
Models
Tools
Retrieval
Memory
MCP
Artifacts
Evaluation
```

The key distinction is:

> **Agents are optimized for dynamic reasoning and decision-making. Workflows are optimized for explicit, controlled orchestration.**

A workflow may invoke an agent, and an agent may use capabilities exposed by the platform, but neither should silently replace the responsibility of the other.

---

# 12. Artifacts

Artifacts represent files and durable outputs produced or consumed by NEXUS.

Examples:

- Uploaded documents
- Generated documents
- Images
- Reports
- Datasets
- Evaluation outputs
- Intermediate execution files

Responsibilities:

- Artifact metadata
- Artifact lifecycle
- Storage references
- Upload/download abstractions
- Associations with executions, agents, workflows, or knowledge sources
- Versioning where required

Actual persistence is provided through infrastructure interfaces.

Artifact flow may look like:

```text
User Upload
    │
    ▼
Artifact
    │
    ├──► RAG Ingestion
    │
    └──► Application Processing
```

Generated output:

```text
Agent / Workflow
      │
      ▼
Generated Artifact
      │
      ▼
Object Storage
```

---

# 13. Evaluation

Evaluation provides mechanisms for measuring AI system behavior.

Responsibilities:

- Evaluation definitions
- Evaluation datasets
- Test cases
- Evaluators
- Metrics
- Scoring
- Regression detection
- Evaluation runs
- Evaluation results

Evaluation may consume:

- Models
- Agents
- Retrieval
- Workflows
- Artifacts

Evaluation should support both:

```text
Offline evaluation
    │
    ├── datasets
    ├── benchmarks
    └── regression tests

Execution evaluation
    │
    ├── agent runs
    ├── workflow runs
    └── production traces where appropriate
```

Evaluation remains conceptually separate from Observability:

- **Evaluation asks:** How well did the system perform?
- **Observability asks:** What happened during execution?

---

# 14. Observability

Observability provides visibility into platform execution.

Responsibilities:

- Logs
- Metrics
- Traces
- Execution events
- Model usage
- Tool execution
- Retrieval activity
- Agent execution
- Workflow execution
- Errors
- Performance measurements
- Correlation identifiers

Observability is cross-cutting and should be accessible to platform modules without creating circular dependencies.

Platform modules emit structured observability information through stable contracts.

Infrastructure determines where logs, metrics, and traces are stored or exported.

---

# 15. Event Architecture

NEXUS uses a platform-level event model for execution visibility and streaming.

Events are transport-independent.

Examples:

```text
execution.started
execution.queued
execution.completed
execution.failed
execution.cancelled

agent.started
agent.message
agent.completed

model.started
model.delta
model.completed

tool.started
tool.completed
tool.failed

retrieval.started
retrieval.completed

workflow.started
workflow.step.started
workflow.step.completed
workflow.completed

artifact.created

evaluation.started
evaluation.completed
```

Events may be consumed by:

- Streaming transport
- Observability
- Execution state tracking
- User interfaces
- Audit systems
- Future event-driven components

The platform must not depend directly on SSE or another transport.

---

# 16. Streaming Architecture

Streaming is required for interactive AI execution.

The architecture separates:

1. Execution
2. Event generation
3. Event transport
4. Client rendering

Conceptually:

```text
                    Agent / Workflow
                           │
                           ▼
                    Platform Events
                           │
                           ▼
                    Event Stream
                           │
                           ▼
                         FastAPI
                           │
                          SSE
                           │
                           ▼
                 React + TypeScript
```

The event model remains independent of the transport.

This allows future transports to be introduced without changing the underlying execution model.

---

# 17. Execution Architecture

Every significant AI operation should have an identifiable execution lifecycle.

Conceptually:

```text
created
   │
   ▼
queued
   │
   ▼
running
   │
   ├──────────────► cancelled
   │
   ├──────────────► failed
   │
   ▼
completed
```

An execution should have:

- Unique execution ID
- Creation timestamp
- Start timestamp where applicable
- Completion timestamp where applicable
- Current status
- Parent execution where applicable
- Error information when failed
- Correlation information
- Relevant usage information

Executions provide a common lifecycle model for:

- Agents
- Workflows
- RAG ingestion
- Evaluations
- Long-running tools
- Other background operations

---

# 18. Synchronous Operations

Operations should be synchronous when the caller requires an immediate result and execution is expected to complete within the normal request lifecycle.

Examples:

```text
Authentication
Configuration retrieval
Simple CRUD
Validation
Metadata queries
Short retrieval queries
Short tool executions
```

Flow:

```text
React
 │
 ▼
FastAPI
 │
 ▼
Application
 │
 ▼
Platform
 │
 ▼
Interface
 │
 ▼
Infrastructure
 │
 ▼
Response
```

---

# 19. Asynchronous Operations

Long-running or resource-intensive operations should use asynchronous execution.

Examples:

```text
Long agent runs
Complex workflows
Large document ingestion
Embedding/indexing
Batch evaluation
Large artifact processing
Long-running external tools
Scheduled work
```

Conceptual flow:

```text
React
 │
 ▼
FastAPI
 │
 ▼
Application
 │
 ├──────────────► Queue / Execution System
 │                       │
 │                       ▼
 │                  Worker / Executor
 │                       │
 │                       ▼
 │                  AI Platform
 │                       │
 │                       ▼
 │                  Interfaces
 │                       │
 │                       ▼
 │                 Infrastructure
 │
 └──────────────► Execution ID
```

The initial request should return an execution identifier rather than unnecessarily holding the HTTP connection open.

---

# 20. Background Workers

Background execution provides the runtime for asynchronous operations.

Workers may execute:

- Agent runs
- Workflow runs
- Document ingestion
- Embedding/indexing
- Evaluations
- Long-running tools
- Artifact processing

The worker runtime should use the same Application and AI Platform contracts as synchronous execution.

The distinction is execution mode, not a separate business implementation.

```text
Synchronous
    │
    └── Application → Platform

Asynchronous
    │
    └── Application → Execution System → Worker → Platform
```

This avoids maintaining two independent implementations of platform behavior.

---

# 21. Cancellation

Long-running operations should support cancellation where technically possible.

Conceptual flow:

```text
React
 │
 ▼
FastAPI
 │
 ▼
Application
 │
 ▼
Execution Controller
 │
 ▼
Agent / Workflow / Worker
```

Cancellation should propagate to active model, tool, workflow, retrieval, or worker operations where supported.

Cancellation must result in a defined terminal execution state.

---

# 22. External Services

External services are accessed through infrastructure adapters.

Examples:

```text
LLM Providers
Embedding Providers
Vector Database
PostgreSQL / Database
Object Storage
Cache
Message Broker
MCP Servers
Third-Party APIs
Observability Backends
```

Provider-specific behavior is isolated behind interfaces.

Example:

```text
Agent
  │
  ▼
Model Interface
  │
  ▼
Provider Adapter
  │
  ▼
External Model API
```

The Agent must not know how a provider SDK works.

---

# 23. Data and Context Flow

A typical interactive AI request follows:

```text
User
 │
 ▼
React + TypeScript
 │
 ▼
FastAPI
 │
 ▼
Application Use Case
 │
 ▼
Agent / Workflow
 │
 ├──► Memory
 │
 ├──► Retrieval / RAG
 │
 ├──► Tools
 │
 ├──► MCP
 │
 └──► Model
          │
          ▼
       Response
          │
          ▼
     Platform Events
          │
          ▼
       FastAPI
          │
          ▼
React + TypeScript
```

The exact path depends on the execution.

Not every request uses every capability.

---

# 24. Security Architecture

Security is a cross-layer concern.

## 24.1 Authentication

Authentication is established at the API boundary.

The system must identify the authenticated principal before executing protected operations.

---

## 24.2 Authorization

Authorization must exist at both transport and application boundaries.

The Application Layer is responsible for resource-level authorization and business authorization rules.

Examples include authorization for:

- Agents
- Workflows
- Documents
- Knowledge sources
- Memory
- Artifacts
- Executions
- Tools

---

## 24.3 Tenant and User Isolation

Where multi-tenancy applies, execution context should preserve relevant ownership information.

Conceptually:

```text
Tenant
  │
  └── User
       │
       ├── Sessions
       ├── Agents
       ├── Knowledge
       ├── Memory
       ├── Artifacts
       └── Executions
```

Data access must respect ownership and authorization boundaries throughout the system.

---

## 24.4 RAG Security

RAG must not bypass document-level or knowledge-source authorization.

The retrieval pipeline should enforce access controls before content is supplied to an Agent or Model.

Conceptually:

```text
Query
 │
 ▼
Authorization Context
 │
 ▼
Retrieval
 │
 ▼
Authorized Results
 │
 ▼
Context
 │
 ▼
Model
```

The system must not rely solely on the model to enforce access control.

---

## 24.5 Tool Security

Tools represent potentially privileged actions and therefore require explicit policy controls.

Tool execution should consider:

- Authorization
- Tool availability
- Input validation
- Resource scope
- Timeouts
- Rate limits
- Audit information
- Side effects

The model deciding to call a tool does not itself constitute authorization to execute it.

---

## 24.6 MCP Security

MCP servers and their exposed capabilities are external trust boundaries.

MCP integrations must be subject to:

- Authentication where applicable
- Authorization
- Capability restrictions
- Input validation
- Timeouts
- Error handling
- Auditing
- Network/security policy

External MCP capabilities must not automatically receive unrestricted access to NEXUS resources.

---

## 24.7 Secrets

Secrets and credentials belong to infrastructure/security boundaries.

Secrets must not be:

- Embedded in frontend code
- Returned through normal API responses
- Stored in source control
- Passed unnecessarily between layers

---

## 24.8 Prompt Injection and Untrusted Content

Documents, retrieved content, tool outputs, MCP resources, and external data must be treated as potentially untrusted input.

The architecture should distinguish:

```text
System / Application Policy
        │
        ▼
Trusted Instructions
        │
        ▼
Untrusted External Content
```

Retrieved or externally supplied content must not automatically override system, application, authorization, or tool policies.

---

## 24.9 Auditability

Security-sensitive actions should produce auditable events where appropriate.

Examples:

```text
Authentication
Authorization decision
Tool execution
MCP operation
Document access
Artifact access
Agent execution
Configuration changes
```

---

# 25. Rate Limiting and Quotas

NEXUS should support rate and resource controls at appropriate boundaries.

Potential limits include:

- API requests
- Model requests
- Tokens
- Tool executions
- RAG ingestion
- Storage
- Concurrent executions
- Workflow executions

Limits may apply at user, tenant, application, provider, or system scope.

Rate limiting and quotas should be represented through platform/application policies rather than hard-coded into individual features.

---

# 26. Caching

Caching may be used to improve performance and reduce repeated external work.

Potential cacheable information includes:

- Model metadata
- Retrieval results where safe
- Embeddings where appropriate
- Configuration
- Provider responses where explicitly safe
- Frequently accessed application data

Caching must not violate:

- Authorization
- Tenant isolation
- Data freshness requirements
- Privacy requirements

The cache is an optimization and must not become the authoritative source of business state unless explicitly designed as such.

---

# 27. Usage and Cost Tracking

AI execution should expose usage information where available.

Relevant information includes:

```text
Model
Provider
Input tokens
Output tokens
Total tokens
Latency
Tool executions
Retrieval operations
Execution ID
Agent / Workflow
User / Tenant
Estimated cost where available
```

Usage information should be associated with the relevant execution.

Conceptually:

```text
Execution
   │
   ├── Model Usage
   ├── Tool Usage
   ├── Retrieval Usage
   ├── Duration
   └── Cost Information
```

This information supports:

- Observability
- Evaluation
- Capacity planning
- Quotas
- Cost analysis
- Product analytics

---

# 28. Failure Handling

Failures must be handled at the appropriate architectural boundary.

## 28.1 Validation Failures

Invalid input should be rejected at the API boundary where possible.

The application layer should still enforce important business invariants.

---

## 28.2 Authentication and Authorization Failures

Protected operations must be rejected when authentication or authorization requirements are not satisfied.

These failures must not reach model, tool, retrieval, or infrastructure execution.

---

## 28.3 Provider Failures

External provider failures must be translated into platform-level errors.

Examples:

```text
ModelUnavailable
ProviderTimeout
RateLimited
ExternalServiceUnavailable
ProviderAuthenticationFailed
```

Provider-specific exceptions must not leak through public API contracts.

---

## 28.4 Retryable Failures

Transient failures may be retried when the operation is safe to retry.

Examples:

- Temporary network failures
- Provider timeouts
- Temporary service unavailability
- Rate limiting

Retries must use bounded attempts and appropriate backoff.

Retries must not create duplicate side effects.

---

## 28.5 Non-Retryable Failures

Permanent failures should fail without repeated retries.

Examples:

- Invalid configuration
- Invalid tool arguments
- Unsupported capability
- Invalid workflow definition
- Authorization failure

---

## 28.6 Partial Failures

Complex workflows and agent executions may contain multiple operations.

A failure in one operation should preserve sufficient execution state to determine:

- What completed
- What failed
- What remains
- Whether recovery is possible
- Whether retrying is safe

The system should avoid representing complex executions as a single opaque success/failure result.

---

## 28.7 Long-Running Execution Failures

Long-running executions must persist failure state.

Conceptually:

```text
Execution
├── status: failed
├── error code
├── error information
├── failure timestamp
└── relevant execution metadata
```

The client must be able to determine:

- Whether execution failed
- Why it failed
- Whether it can be retried
- The execution state at failure

---

# 29. Reliability and Idempotency

Operations that can be retried or submitted more than once should define their idempotency behavior.

Particularly important for:

- Document ingestion
- Artifact creation
- Workflow execution
- Tool operations with side effects
- External API calls
- Background jobs

The architecture should distinguish between:

```text
Read / Safe operation
        vs.
Side-effecting operation
```

Retries must be designed around this distinction.

---

# 30. Observability and Correlation

Every significant request and execution should be traceable across architectural boundaries.

Correlation context should propagate through:

```text
React
  ↓
FastAPI
  ↓
Application
  ↓
AI Platform
  ↓
Worker
  ↓
Infrastructure
  ↓
External Provider
```

Where supported, the system should correlate:

- Request ID
- Execution ID
- Workflow ID
- Agent ID
- Tool execution ID
- Model call ID
- Retrieval operation ID
- Trace ID
- Tenant/user context where appropriate

This allows a single user operation to be reconstructed across the system.

---

# 31. Interfaces

Interfaces define boundaries between the platform and external implementations.

Examples include:

```text
ModelProvider
EmbeddingProvider
VectorStore
Repository
ObjectStorage
Cache
MessageBroker
MCPTransport
ExternalService
EventSink
ObservabilitySink
```

The interface belongs to the layer that owns the abstraction.

Infrastructure implements the interface.

Example:

```text
Retrieval
   │
   ▼
VectorStore Interface
   │
   ▼
Vector Database Implementation
```

This allows infrastructure to be replaced without changing retrieval behavior.

---

# 32. Dependency Direction

Dependency direction is a core architectural constraint.

The intended system-level dependency flow is:

```text
Frontend
   │
   ▼
FastAPI
   │
   ▼
Application
   │
   ▼
AI Platform
   │
   ▼
Interfaces
   │
   ▼
Infrastructure
```

Within the AI Platform:

```text
                    Core
                     ▲
                     │
          ┌──────────┼──────────┐
          │          │          │
       Models    Interfaces   Observability
          ▲          ▲
          │          │
    ┌─────┼──────────┼───────────────┐
    │     │          │               │
 Retrieval Agents   Tools          Memory
    │     │          │               │
    └─────┼──────────┼───────────────┘
          │          │
       Workflows     MCP
          │
          ▼
      Evaluation
          │
          ▼
      Artifacts
```

The exact internal dependency graph must remain acyclic.

### Dependency rules

1. Lower-level modules must not import higher-level modules.
2. Infrastructure must implement abstractions rather than define application behavior.
3. Concrete providers must not leak into application contracts.
4. API handlers must not directly access infrastructure.
5. Modules communicate through stable contracts.
6. Circular dependencies are prohibited.
7. Shared abstractions belong in the lowest appropriate layer.
8. A module must not depend on another module merely to reuse unrelated utility code.
9. Infrastructure implementations must be replaceable without changing application use cases.
10. Platform modules should remain independently testable and reusable where practical.

---

# 33. Data Ownership

The architecture should establish clear ownership of major concepts.

At a conceptual level:

```text
Application / Domain
├── Users / Tenants
├── Applications
├── Agents
├── Workflows
├── Sessions
├── Executions
├── Knowledge Sources
├── Memories
├── Artifacts
└── Evaluation Runs
```

Platform modules operate on these concepts through defined contracts.

Infrastructure provides persistence but should not redefine ownership semantics.

---

# 34. Configuration

Configuration flows from the application/runtime boundary toward the platform and infrastructure.

Conceptually:

```text
Runtime Configuration
        │
        ▼
Application Context
        │
        ▼
Platform Configuration
        │
        ▼
Provider / Infrastructure Configuration
```

Configuration should distinguish between:

- Application configuration
- Platform configuration
- Provider configuration
- Secrets
- Runtime policies

Sensitive credentials remain within appropriate security/infrastructure boundaries.

---

# 35. Architecture Boundaries

The architecture deliberately separates:

```text
Transport
    ↓
Application use cases
    ↓
AI capabilities
    ↓
Stable interfaces
    ↓
Concrete infrastructure
```

Within the AI Platform:

```text
Reasoning       → Agents
Orchestration   → Workflows
Knowledge       → Retrieval / RAG
Actions         → Tools
External MCP    → MCP
Context         → Memory
Outputs         → Artifacts
Quality         → Evaluation
Visibility      → Observability
Model access    → Models
Foundation      → Core
```

This separation is intended to keep responsibilities clear and prevent the platform from becoming a monolithic AI runtime.

---

# 36. Architectural Constraints

The following constraints are mandatory.

### Constraint 1 — No provider leakage

Application and platform consumers must not depend directly on concrete AI provider SDKs.

### Constraint 2 — Thin API layer

FastAPI endpoints must delegate behavior to application use cases.

### Constraint 3 — Infrastructure isolation

Application and platform code must communicate with infrastructure through interfaces.

### Constraint 4 — No circular dependencies

The dependency graph must remain acyclic.

### Constraint 5 — Transport independence

AI execution must not depend on HTTP or SSE implementation details.

### Constraint 6 — Execution identity

Long-running operations must have durable execution identity and state.

### Constraint 7 — Structured errors

Errors must be represented through stable platform/application error contracts.

### Constraint 8 — Replaceable infrastructure

External providers and infrastructure implementations must be replaceable without redesigning application use cases.

### Constraint 9 — Explicit asynchronous boundaries

Operations that can exceed normal request lifetimes must use an asynchronous execution model.

### Constraint 10 — Observability by design

Execution tracing and correlation must be part of the architecture rather than added afterward.

### Constraint 11 — Security before execution

Authorization and capability policies must be evaluated before privileged operations execute.

### Constraint 12 — RAG access control

Retrieval must respect document and knowledge-source authorization before context reaches a model.

### Constraint 13 — Untrusted content isolation

External content, retrieved documents, tool results, and MCP resources must not override system or application policy.

### Constraint 14 — Side-effect awareness

Retry and execution behavior must account for operations that create external side effects.

### Constraint 15 — Platform contracts

Modules must communicate through explicit contracts rather than hidden cross-module coupling.

---

# 37. Target System Model

The final conceptual model is:

```text
                         ┌───────────────────────┐
                         │ React + TypeScript    │
                         └───────────┬───────────┘
                                     │
                                  API/SSE
                                     │
                                     ▼
                         ┌───────────────┐
                         │    FastAPI    │
                         └───────┬───────┘
                                 │
                                 ▼
                      ┌─────────────────────┐
                      │ Application Layer   │
                      └──────────┬──────────┘
                                 │
                                 ▼
              ┌────────────────────────────────────┐
              │          AI Platform / SDK          │
              │                                    │
              │ Core                               │
              │ Models                             │
              │ Retrieval ───────► RAG             │
              │ Agents                             │
              │ Tools                              │
              │ MCP                                │
              │ Memory                             │
              │ Workflows                          │
              │ Artifacts                           │
              │ Evaluation                         │
              │ Observability                      │
              └────────────────┬───────────────────┘
                               │
                               ▼
                       ┌───────────────┐
                       │  Interfaces   │
                       └───────┬───────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │   Infrastructure    │
                    │                     │
                    │ Database            │
                    │ Cache               │
                    │ Queue               │
                    │ Object Storage      │
                    │ Vector Store        │
                    │ AI Providers        │
                    │ MCP Servers         │
                    │ External APIs       │
                    │ Observability       │
                    └─────────────────────┘
```

The architecture supports three major execution patterns:

```text
1. Synchronous request
   React → API → Application → Platform → Response

2. Streaming execution
   React ← SSE ← API ← Events ← Platform Execution

3. Asynchronous execution
   React → API → Execution → Worker → Platform
```

RAG, Agents, Tools, MCP, Memory, Workflows, Artifacts, Evaluation, and Observability operate as coordinated platform capabilities rather than independent application implementations.

---

# 38. Architecture Decision Summary

| Area | Decision |
|---|---|
| Web client | React + TypeScript + Vite |
| Backend API | FastAPI |
| Application orchestration | Dedicated Application Layer |
| AI foundation | Modular AI Platform / SDK |
| AI modules | Core, Models, Retrieval, Agents, Tools, MCP, Memory, Workflows, Artifacts, Evaluation, Observability |
| RAG | First-class Retrieval capability with ingestion and query-time pipelines |
| Provider integration | Interfaces and infrastructure adapters |
| Persistence | Infrastructure implementations behind interfaces |
| Long-running execution | Asynchronous execution model |
| Browser streaming | SSE initially |
| Event model | Transport-independent platform events |
| Agent execution | Dynamic reasoning and capability use |
| Workflow execution | Deterministic multi-step orchestration |
| Tools | Explicit executable capabilities with authorization and validation |
| MCP | Isolated protocol integration behind platform contracts |
| Memory | Persistent contextual information distinct from RAG |
| Artifacts | Durable files and execution outputs |
| Evaluation | Offline and execution-based quality measurement |
| Observability | Cross-layer logs, metrics, traces, and execution events |
| Security | Cross-layer authentication, authorization, isolation, and policy enforcement |
| RAG security | Access control before context reaches models |
| Errors | Structured platform/application errors |
| Retries | Bounded and safe for transient/idempotent operations |
| Cancellation | Supported for long-running executions where possible |
| Rate limits | Application/platform policies |
| Caching | Optimization behind infrastructure interfaces |
| Usage tracking | Execution-level model, tool, retrieval, latency, and cost information |
| Dependency direction | Toward stable abstractions |
| Circular dependencies | Prohibited |
| Infrastructure coupling | Prohibited above interface boundary |
| API responsibility | Transport and request boundary |
| Business orchestration | Application Layer |
| AI orchestration | AI Platform |
| External integrations | Infrastructure |

---

# 39. Implementation Boundary

This architecture is considered complete at the architectural level when the following are clearly defined:

- Layer boundaries
- Platform module boundaries
- RAG boundaries
- Agent and workflow responsibilities
- Tool and MCP boundaries
- Memory boundaries
- Dependency direction
- Interface ownership
- Execution lifecycle
- Synchronous and asynchronous execution
- Streaming and event model
- Security boundaries
- External service boundaries
- Data and artifact flow
- Failure semantics
- Observability model
- Usage and cost model

The following are intentionally **not** defined here:

- Exact Python package structure
- Exact class names
- Exact database schemas
- Exact API endpoint specifications
- Exact provider SDK implementations
- Exact deployment topology
- Exact queue technology
- Exact vector database technology
- Exact frontend component structure

Those details belong in implementation and contract documentation.

> **Architecture defines the constraints and responsibilities. Implementation realizes those constraints.**