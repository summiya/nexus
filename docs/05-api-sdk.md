# Nexus AI — Python AI Capability and REST API Contracts

**Document:** `docs/05-api-sdk.md`  
**Document Type:** Canonical technical specification  
**Audience:** AI coding agents, backend engineers, architects, platform engineers, security engineers  
**Status:** Implemented LLM/Conversation baseline with clearly marked future targets

**Primary backend:** Python + FastAPI  
**Primary language:** Python 3.12+  
**Primary database:** PostgreSQL  
**Vector storage/search:** PostgreSQL + pgvector  

---

## 1. Purpose

This document records the implemented provider-independent LLM boundary and public Conversation API, then preserves target contracts for capabilities that have not yet been built.

Only sections explicitly marked **Implemented** describe the current repository and are authoritative for current behavior. Sections marked **Future target**, and unmarked capability requirements retained from the broader platform design, are design direction only: they must not be treated as existing packages, routes, or behavior, and they do not authorize implementation outside an approved task.

The current LLM capability provides stable, vendor-neutral interfaces for model generation and streaming. Future targets in this document cover:

- LLM providers
- Model routing
- Retrieval
- Embeddings
- Tools
- Agents
- Memory
- MCP
- Streaming
- Observability
- Errors and retries
- Security and permission enforcement

Vendor-specific SDKs, APIs, protocols, authentication mechanisms, request formats, and response formats **must remain behind these interfaces**.

The application layer must not directly depend on OpenAI, Anthropic, Google, Azure, Ollama, LiteLLM, MCP server implementations, or other vendor SDKs.

---

# 2. Design Principles

The SDK must follow these principles.

## 2.1 Vendor neutrality

Core Nexus code must depend on Nexus interfaces rather than vendor SDKs.

```text
Application
    |
    v
Nexus SDK Interfaces
    |
    +---- OpenAI Adapter
    +---- Anthropic Adapter
    +---- Google Adapter
    +---- Azure Adapter
    +---- Local Model Adapter
    +---- Other Provider Adapters
```

A provider may be replaced without changing application-level agent logic.

---

## 2.2 Async-first

All network, model, retrieval, embedding, tool, and MCP operations must support asynchronous execution.

Use:

```python
async def ...
```

Synchronous wrappers may be provided where useful, but async APIs are canonical.

---

## 2.3 Strong typing

Use Python type hints throughout the SDK.

Preferred technologies:

- `dataclasses`
- `typing`
- `typing.Protocol`
- Pydantic models where runtime validation is required
- `Enum` / `StrEnum` for constrained values

Avoid untyped dictionaries as public contracts.

Provider-specific response objects must be normalized into Nexus SDK types.

---

## 2.4 Streaming-first architecture

The SDK must support:

- non-streaming completion
- token streaming
- structured events
- tool-call events
- reasoning/status events where available
- agent lifecycle events

Streaming must not require a separate provider-specific API at the application layer.

---

## 2.5 Cancellation

Long-running operations must support cancellation.

```python
await provider.complete(
    request,
    cancellation_token=token,
)
```

Cancellation must propagate to:

- LLM requests
- retrieval
- embeddings
- tools
- agents
- MCP calls

---

## 2.6 Context propagation

SDK operations should carry a request context containing:

- request ID
- tenant ID
- project ID
- user ID
- agent ID
- conversation ID
- trace ID
- permission context
- deadline
- metadata

Security-sensitive context must never be inferred from untrusted model output.

---

# 3. Implemented LLM Package Architecture

The current provider-independent LLM capability is feature-first:

```text
backend/src/nexus/llm/
├── application/
│   └── model_policy.py
├── domain/
│   ├── messages.py
│   ├── requests.py
│   ├── responses.py
│   ├── events.py
│   ├── errors.py
│   ├── tools.py
│   └── usage.py
├── ports/
│   └── gateway.py
└── infrastructure/
    ├── gateway_factory.py
    └── adapters/litellm/
```

Application code depends on the domain contracts and `LLMGateway`. Concrete provider selection and LiteLLM mapping remain in infrastructure and composition.

---

# 4. Future Target: Trusted Request Context

A shared SDK-wide `RequestContext` has not been implemented. Future retrieval, agent, tool, and MCP capabilities may require a trusted context carrying request, organization, project, user, trace, deadline, and permission information. Such values must come from trusted server state and must never be overwritten by model output or untrusted request fields.

---

# 5. Implemented LLM Message Contract

Providers normalize messages into the immutable `LLMMessage` contract:

```python
class LLMRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True)
class LLMMessage:
    role: LLMRole
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
```

Tool messages require a tool-call ID. Provider SDK message objects must not cross this boundary. Multimodal content and a developer role are future targets, not current fields.

---

# 6. Implemented `LLMGateway`

`LLMGateway` is the current provider-independent model execution port:

```python
class LLMGateway(Protocol):
    async def generate(self, request: LLMRequest) -> LLMResponse: ...

    def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]: ...
```

It owns no application authorization, tenant persistence, Conversation lifecycle, or business orchestration. The `LiteLLMAdapter` implements this port, translates provider failures into Nexus LLM errors, owns the raw provider iterator, and exposes only normalized Nexus responses and events.

---

# 7. Implemented `LLMRequest`

```python
@dataclass(frozen=True)
class LLMRequest:
    model: str
    messages: Sequence[LLMMessage]
    temperature: float | None = None
    max_output_tokens: int | None = None
    tools: Sequence[LLMToolDefinition] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
```

The contract requires a model and at least one message. Provider adapters translate it into provider-specific request shapes. Additional routing, response-format, and stop controls are future targets unless added through an approved contract change.

---

# 8. Implemented `LLMResponse`

```python
@dataclass(frozen=True)
class LLMResponse:
    message: LLMMessage
    finish_reason: LLMFinishReason = LLMFinishReason.UNKNOWN
    usage: LLMUsage | None = None
    tool_calls: Sequence[LLMToolCall] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
```

Finish reasons are normalized as `stop`, `length`, `tool_calls`, `content_filter`, `error`, or `unknown`. Provider identifiers and raw response objects are not part of the application-facing response.

---

# 9. Implemented Normalized LLM Events

`LLMGateway.stream()` returns `AsyncIterator[LLMEvent]`, where `LLMEvent` is the union of:

- `LLMStartedEvent`;
- `LLMTextDeltaEvent`;
- `LLMToolCallStartedEvent`;
- `LLMToolCallDeltaEvent`;
- `LLMToolCallCompletedEvent`;
- `LLMUsageEvent`;
- `LLMCompletedEvent`;
- `LLMErrorEvent`.

Applications consume these typed events without importing LiteLLM or another provider SDK. Provider metadata may be retained only in the normalized contracts intended for it.

---

# 10. Implemented Model Policy and Future Routing

The current `ModelPolicy` accepts only model identifiers present in the configured allowlist. Nexus does not currently implement a `ModelRouter`, provider registry, health-based routing, cost routing, tenant routing, or model-list API. Those remain future targets and must not be inferred from the current allowlist.

---

# Future Capability Targets

Sections 11–79 describe possible contracts for retrieval, embeddings, tools, agents, memory, MCP, runtime orchestration, policy, observability, and related platform capabilities. They are not implemented unless a section explicitly says otherwise.

# 11. RetrievalProvider

## 11.1 Responsibility

Provides semantic and hybrid retrieval over Nexus knowledge.

Supports:

- vector search
- keyword search
- metadata filtering
- hybrid search
- reranking
- tenant isolation
- project isolation

---

## 11.2 Interface

```python
class RetrievalProvider(Protocol):

    async def search(
        self,
        request: RetrievalRequest,
        *,
        context: RequestContext,
    ) -> RetrievalResponse:
        ...

    async def health_check(
        self,
        *,
        context: RequestContext,
    ) -> ProviderHealth:
        ...
```

---

# 12. RetrievalRequest

```python
@dataclass(frozen=True)
class RetrievalRequest:
    query: str
    top_k: int = 10

    project_id: str | None = None

    filters: dict[str, Any] = field(default_factory=dict)

    search_type: str = "hybrid"

    include_content: bool = True
    include_metadata: bool = True

    rerank: bool = True
```

Security rule:

`project_id` supplied by the caller must be validated against the trusted request context.

A model-generated project ID must never be trusted.

---

# 13. RetrievalResult

```python
@dataclass(frozen=True)
class RetrievalResult:
    document_id: str
    chunk_id: str

    score: float

    content: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)
```

The retrieval layer must preserve source identity for citations and auditability.

---

# 14. EmbeddingProvider

## 14.1 Responsibility

Provides normalized text embedding functionality.

---

## 14.2 Interface

```python
class EmbeddingProvider(Protocol):

    @property
    def provider_name(self) -> str:
        ...

    async def embed(
        self,
        request: EmbeddingRequest,
        *,
        context: RequestContext,
    ) -> EmbeddingResponse:
        ...

    async def health_check(
        self,
        *,
        context: RequestContext,
    ) -> ProviderHealth:
        ...
```

---

# 15. EmbeddingRequest

```python
@dataclass(frozen=True)
class EmbeddingRequest:
    model: str
    inputs: list[str]

    dimensions: int | None = None

    metadata: dict[str, Any] = field(default_factory=dict)
```

---

# 16. EmbeddingResponse

```python
@dataclass(frozen=True)
class EmbeddingResponse:
    model: str
    provider: str

    embeddings: list[list[float]]

    usage: Usage | None = None
```

Embedding dimensions must be validated before persistence.

---

# 17. Tool

## 17.1 Responsibility

A `Tool` represents an executable capability exposed to an agent.

Examples:

- web search
- database query
- file access
- HTTP request
- code execution
- internal Nexus operation
- external service integration

---

## 17.2 Interface

```python
class Tool(Protocol):

    @property
    def definition(self) -> ToolDefinition:
        ...

    async def execute(
        self,
        request: ToolExecutionRequest,
        *,
        context: RequestContext,
    ) -> ToolResult:
        ...
```

---

# 18. ToolDefinition

```python
@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str

    input_schema: dict[str, Any]

    version: str = "1"
```

Tool names must be unique within their registry scope.

---

# 19. ToolExecutionRequest

```python
@dataclass(frozen=True)
class ToolExecutionRequest:
    tool_name: str
    arguments: dict[str, Any]

    call_id: str

    timeout_ms: int | None = None
```

---

# 20. ToolResult

```python
@dataclass(frozen=True)
class ToolResult:
    call_id: str

    success: bool

    content: str | None = None

    structured_data: Any | None = None

    error: ToolError | None = None

    metadata: dict[str, Any] = field(default_factory=dict)
```

Tools must never receive more credentials or permissions than required.

---

# 21. Agent

## 21.1 Responsibility

An `Agent` coordinates:

- model interaction
- tools
- retrieval
- memory
- planning
- execution
- lifecycle events

The agent is an orchestration boundary, not a model provider.

---

## 21.2 Interface

```python
class Agent(Protocol):

    @property
    def agent_id(self) -> str:
        ...

    @property
    def name(self) -> str:
        ...

    async def run(
        self,
        request: AgentRequest,
        *,
        context: RequestContext,
    ) -> AgentResponse:
        ...

    async def stream(
        self,
        request: AgentRequest,
        *,
        context: RequestContext,
    ) -> AsyncIterator[AgentEvent]:
        ...
```

---

# 22. AgentRequest

```python
@dataclass(frozen=True)
class AgentRequest:
    input: str

    conversation_id: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)
```

The request must not allow the caller to arbitrarily elevate:

- tools
- model permissions
- MCP permissions
- project access
- system instructions

---

# 23. AgentResponse

```python
@dataclass(frozen=True)
class AgentResponse:
    output: str

    conversation_id: str | None = None

    tool_calls: list[ToolCall] = field(default_factory=list)

    citations: list[Citation] = field(default_factory=list)

    usage: Usage | None = None

    metadata: dict[str, Any] = field(default_factory=dict)
```

---

# 24. Agent Lifecycle

Recommended events:

```text
agent.started
agent.thinking
agent.tool_requested
agent.tool_started
agent.tool_completed
agent.model_started
agent.model_delta
agent.model_completed
agent.completed
agent.failed
agent.cancelled
```

Internal reasoning must not automatically be exposed to end users.

---

# 25. MemoryProvider

## 25.1 Responsibility

Provides persistent and retrievable agent/conversation memory.

Memory may include:

- conversation history
- user-approved preferences
- agent state
- project context
- summaries
- long-term semantic memories

Memory must respect tenant and project isolation.

---

## 25.2 Interface

```python
class MemoryProvider(Protocol):

    async def get(
        self,
        request: MemoryQuery,
        *,
        context: RequestContext,
    ) -> MemoryResponse:
        ...

    async def store(
        self,
        request: MemoryWriteRequest,
        *,
        context: RequestContext,
    ) -> MemoryRecord:
        ...

    async def delete(
        self,
        memory_id: str,
        *,
        context: RequestContext,
    ) -> None:
        ...
```

---

# 26. MemoryQuery

```python
@dataclass(frozen=True)
class MemoryQuery:
    query: str | None = None

    conversation_id: str | None = None
    project_id: str | None = None

    limit: int = 20
```

---

# 27. MemoryRecord

```python
@dataclass(frozen=True)
class MemoryRecord:
    id: str

    memory_type: str

    content: str

    tenant_id: str
    project_id: str | None

    conversation_id: str | None

    metadata: dict[str, Any] = field(default_factory=dict)
```

Memory writes should have explicit provenance.

Recommended metadata:

```text
source
created_by
created_at
confidence
consent
expires_at
```

---

# 28. MCPProvider

## 28.1 Responsibility

`MCPProvider` is the Nexus abstraction over Model Context Protocol integrations.

It provides access to:

- MCP servers
- resources
- prompts
- tools
- server capabilities

Vendor/client-specific MCP implementations remain behind this boundary.

---

## 28.2 Interface

```python
class MCPProvider(Protocol):

    async def list_servers(
        self,
        *,
        context: RequestContext,
    ) -> list[MCPServer]:
        ...

    async def list_tools(
        self,
        server_id: str,
        *,
        context: RequestContext,
    ) -> list[ToolDefinition]:
        ...

    async def call_tool(
        self,
        request: MCPToolCallRequest,
        *,
        context: RequestContext,
    ) -> ToolResult:
        ...

    async def list_resources(
        self,
        server_id: str,
        *,
        context: RequestContext,
    ) -> list[MCPResource]:
        ...
```

---

# 29. MCP Security Boundary

MCP must be treated as an external capability boundary.

Every MCP operation must enforce:

```text
Tenant
  ↓
Project
  ↓
User
  ↓
Agent
  ↓
MCP Server
  ↓
Capability
  ↓
Tool
  ↓
Arguments
```

An MCP server must not automatically inherit unrestricted Nexus privileges.

---

# 30. Provider Registry

Providers should be resolved through registries rather than hard-coded conditionals.

Example:

```python
class ProviderRegistry:

    def register_llm(
        self,
        name: str,
        provider: LLMProvider,
    ) -> None:
        ...

    def get_llm(
        self,
        name: str,
    ) -> LLMProvider:
        ...
```

Similar registries should exist for:

- embeddings
- retrieval
- memory
- MCP
- tools
- agents

---

# 31. Nexus Agent Runtime

The `Agent` interface is intentionally small, but Nexus requires a dedicated runtime
to execute agents, enforce limits and policies, persist execution state, emit events,
and coordinate handoffs between agents.

The runtime is responsible for:

- agent lifecycle
- task execution
- model calls
- tool calls
- retrieval
- memory access
- MCP access
- policy enforcement
- approvals
- retries
- cancellation
- execution limits
- handoffs
- event emission
- persistence hooks
- audit hooks

Provider implementations must never implement the complete agent runtime themselves.

---

## 32. AgentTask

```python
@dataclass(frozen=True)
class AgentTask:
    task_id: str
    agent_id: str

    input: str

    parent_task_id: str | None = None
    conversation_id: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)
```

Tasks are the canonical unit of agent work.

A task must belong to the authenticated tenant and, where applicable, project.

---

# 33. AgentExecution

```python
@dataclass(frozen=True)
class AgentExecution:
    run_id: str
    task_id: str
    agent_id: str

    status: str

    started_at: datetime
    completed_at: datetime | None = None

    iteration_count: int = 0
    tool_call_count: int = 0

    usage: Usage | None = None

    metadata: dict[str, Any] = field(default_factory=dict)
```

Recommended statuses:

```text
queued
running
waiting_for_approval
waiting_for_handoff
completed
failed
cancelled
timed_out
```

Execution state must be persisted by the runtime/persistence layer when durable execution
is enabled.

---

# 34. AgentResult

```python
@dataclass(frozen=True)
class AgentResult:
    run_id: str
    task_id: str

    status: str

    output: str | None = None

    handoff: "AgentHandoff | None" = None

    tool_calls: list[ToolCall] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)

    usage: Usage | None = None

    error: ErrorInfo | None = None

    metadata: dict[str, Any] = field(default_factory=dict)
```

---

# 35. Agent Handoff

Nexus supports multi-agent workflows. An agent may request that another authorized
agent continue a task.

```python
@dataclass(frozen=True)
class AgentHandoff:
    from_agent: str
    to_agent: str

    task_id: str

    reason: str

    input: dict[str, Any]

    parent_run_id: str | None = None
```

A handoff is a **request**, not an authorization decision.

Before execution:

```text
Agent
  ↓
Handoff Request
  ↓
Policy Engine
  ↓
Target Agent Authorization
  ↓
Create Child Task
  ↓
Target Agent
```

The model must never be allowed to arbitrarily select an unauthorized agent.

---

# 36. Agent Runtime Interface

```python
class AgentRuntime(Protocol):

    async def execute(
        self,
        task: AgentTask,
        *,
        context: RequestContext,
    ) -> AgentResult:
        ...

    async def stream(
        self,
        task: AgentTask,
        *,
        context: RequestContext,
    ) -> AsyncIterator["AgentEvent"]:
        ...

    async def cancel(
        self,
        run_id: str,
        *,
        context: RequestContext,
    ) -> None:
        ...
```

The runtime is the canonical orchestration boundary for Nexus agents.

---

# 37. Execution Policy

Agent execution must be controlled by policy rather than by model instructions.

```python
@dataclass(frozen=True)
class ExecutionPolicy:
    limits: ExecutionLimits

    allowed_tools: frozenset[str] = frozenset()
    allowed_mcp_servers: frozenset[str] = frozenset()
    allowed_agents: frozenset[str] = frozenset()

    require_approval_for: frozenset[str] = frozenset()

    allow_external_network: bool = False
    allow_code_execution: bool = False
```

Policies are determined by trusted application/security configuration.

Model output cannot modify the policy.

---

# 38. PolicyEngine

The SDK must provide a formal authorization boundary.

```python
class PolicyEngine(Protocol):

    async def authorize_model(
        self,
        request: CompletionRequest,
        *,
        context: RequestContext,
    ) -> None:
        ...

    async def authorize_tool(
        self,
        request: ToolExecutionRequest,
        *,
        context: RequestContext,
    ) -> None:
        ...

    async def authorize_mcp(
        self,
        request: MCPToolCallRequest,
        *,
        context: RequestContext,
    ) -> None:
        ...

    async def authorize_agent_handoff(
        self,
        handoff: AgentHandoff,
        *,
        context: RequestContext,
    ) -> None:
        ...

    async def requires_approval(
        self,
        operation: str,
        *,
        context: RequestContext,
    ) -> bool:
        ...
```

Authorization must happen outside the model.

The policy engine integrates with:

- authentication
- RBAC
- tenant isolation
- project isolation
- tool permissions
- MCP permissions
- data-access policies
- execution limits

---

# 39. Human Approval

High-risk operations may require explicit approval.

```python
@dataclass(frozen=True)
class ApprovalRequest:
    approval_id: str

    operation: str
    description: str

    run_id: str
    task_id: str

    expires_at: datetime | None = None

    metadata: dict[str, Any] = field(default_factory=dict)
```

Runtime status:

```text
waiting_for_approval
```

An approval must be tied to a specific operation and execution context.

Approval must not grant broader permissions than the approved operation.

---

# 40. Canonical Event Envelope

All runtime events must use a common envelope.

```python
@dataclass(frozen=True)
class AgentEvent:
    event_id: str
    event_type: str

    tenant_id: str
    project_id: str | None

    run_id: str
    task_id: str
    agent_id: str

    sequence: int
    timestamp: datetime

    payload: dict[str, Any] = field(default_factory=dict)
```

Recommended event types:

```text
agent.started
agent.iteration.started
agent.model.requested
agent.model.delta
agent.model.completed
agent.retrieval.started
agent.retrieval.completed
agent.tool.requested
agent.tool.approval_required
agent.tool.started
agent.tool.completed
agent.mcp.requested
agent.handoff.requested
agent.handoff.started
agent.completed
agent.failed
agent.cancelled
```

Events must be ordered within a run using `sequence`.

The event payload must not contain secrets.

---

# 41. Event Sink

Runtime events should be emitted through a pluggable sink.

```python
class EventSink(Protocol):

    async def publish(
        self,
        event: AgentEvent,
        *,
        context: RequestContext,
    ) -> None:
        ...
```

Possible implementations:

```text
InMemoryEventSink
DatabaseEventSink
QueueEventSink
WebhookEventSink
```

The SDK must not require a particular message broker.

---

# 42. Idempotency

External side effects must support idempotency where possible.

Tool and MCP execution requests should carry a stable operation identifier.

```python
@dataclass(frozen=True)
class OperationIdentity:
    operation_id: str
    attempt: int = 1
```

Retries must not unintentionally execute the same external side effect multiple times.

Providers/tools that cannot guarantee idempotency must declare this capability.

---

# 43. Persistence Boundary

The SDK must not directly own PostgreSQL transactions or database sessions.

The dependency direction is:

```text
Agent Runtime
      ↓
SDK Interfaces
      ↓
Application Services
      ↓
Repository Interfaces
      ↓
Persistence Implementation
      ↓
PostgreSQL / pgvector / Object Storage
```

The SDK may expose persistence-related data contracts, but persistence implementations
remain outside provider adapters.

Memory and retrieval providers may internally use repositories, but they must not expose
database-specific objects to callers.

---

# 44. Repository Contract

Where durable agent execution is required, the application may provide repositories such as:

```python
class AgentExecutionRepository(Protocol):

    async def create(
        self,
        execution: AgentExecution,
        *,
        context: RequestContext,
    ) -> None:
        ...

    async def update(
        self,
        execution: AgentExecution,
        *,
        context: RequestContext,
    ) -> None:
        ...

    async def get(
        self,
        run_id: str,
        *,
        context: RequestContext,
    ) -> AgentExecution | None:
        ...
```

Repositories must enforce tenant/project ownership.

---

# 45. Capability Discovery

Providers and tools should expose capabilities without exposing implementation details.

Example:

```python
@dataclass(frozen=True)
class CapabilitySet:
    streaming: bool = False
    tools: bool = False
    structured_output: bool = False
    vision: bool = False
    cancellation: bool = False
```

The router/runtime should use capability discovery rather than checking provider class names.

---

# 46. Provider Health and Circuit Breaking

Provider health must be observable through a normalized contract.

```python
@dataclass(frozen=True)
class ProviderHealth:
    healthy: bool

    latency_ms: int | None = None

    error_rate: float | None = None

    retry_after_seconds: int | None = None

    metadata: dict[str, Any] = field(default_factory=dict)
```

The routing layer may temporarily remove unhealthy providers from candidate routes.

Circuit-breaking state belongs to the routing/infrastructure layer, not provider adapters.

---

# 47. Secret and Credential Boundary

Provider adapters may receive credentials through dependency injection, but credentials:

- must never be part of `CompletionRequest`
- must never be exposed to agents
- must never be exposed to models
- must never appear in event payloads
- must never be written to ordinary logs

Recommended abstraction:

```python
class CredentialProvider(Protocol):

    async def get(
        self,
        credential_ref: str,
        *,
        context: RequestContext,
    ) -> str:
        ...
```

The actual secret store is infrastructure-specific.

---

# 48. Prompt Injection and Untrusted Data

The SDK must explicitly classify these as untrusted:

- user input
- retrieved documents
- web content
- uploaded files
- tool output
- MCP resources
- external API responses
- model-generated tool arguments

Untrusted content must not be able to modify:

- tenant identity
- project identity
- user identity
- permissions
- policy
- credentials
- system configuration

Tool and MCP calls must pass through authorization and validation before execution.

---

# 49. Data Leakage Controls

Provider adapters must support policy-driven controls for sensitive data.

Before external provider calls, the application/security layer may apply:

```text
classification
 ↓
redaction
 ↓
data residency policy
 ↓
provider policy
 ↓
provider request
```

The SDK must provide metadata hooks to identify:

- data classification
- residency requirements
- allowed providers
- retention requirements

The final policy decision remains outside the model.

---

# 50. Multi-Tenant Isolation

Every SDK operation that accesses tenant-scoped resources must receive `RequestContext`.

No provider may infer tenant identity from:

- prompt content
- model output
- tool arguments
- retrieval query
- MCP resource content

Tenant identity comes from trusted authentication/application context.

Project-scoped resources must additionally validate:

```text
tenant_id
project_id
user permissions
agent permissions
```

---

# 51. Agent Handoff Security

Agent-to-agent execution is subject to the same authorization rules as tools.

A handoff must validate:

1. source agent
2. target agent
3. tenant
4. project
5. user
6. task ownership
7. target-agent capability
8. allowed workflow transition
9. execution limits

An agent cannot hand off to an arbitrary privileged agent.

---

# 52. Agent Workflow Compatibility

The SDK must support both:

```text
Single Agent
```

and:

```text
Multi-Agent Workflow
```

Example:

```text
Planner
   ↓
Developer
   ↓
Tester
   ↓
Reviewer
   ↓
Approved
```

The workflow engine may reject, repeat, or reroute a stage:

```text
Developer
   ↓
Tester
   ↓
FAILED
   ↓
Developer
```

Workflow state belongs to the runtime/application layer.

Agents remain reusable units of capability.

---

# 53. Context and Correlation

All nested operations must propagate:

```text
request_id
trace_id
tenant_id
project_id
conversation_id
agent_id
run_id
task_id
```

Example:

```text
HTTP Request
  └── Agent Run
       ├── Model Call
       ├── Retrieval
       ├── Tool Call
       └── MCP Call
```

Each child operation must remain attributable to its parent run.

---

# 54. Dependency Injection

FastAPI dependency injection should provide SDK interfaces to application services.

Example:

```python
@router.post("/chat")
async def chat(
    request: ChatRequest,
    agent: Agent = Depends(get_agent),
):
    return await agent.run(
        AgentRequest(input=request.message),
        context=request_context,
    )
```

Routes must not instantiate vendor clients directly.

Bad:

```python
client = OpenAI(...)
```

inside an API route.

Good:

```python
agent = container.resolve(Agent)
```

---

# 55. Provider Adapters

Each vendor integration should implement the relevant Nexus interface.

Example:

```python
class OpenAILLMProvider:
    async def complete(
        self,
        request: CompletionRequest,
        *,
        context: RequestContext,
    ) -> CompletionResponse:
        ...
```

The adapter is responsible for translating:

```text
Nexus Request
      ↓
Provider Request
      ↓
Provider API
      ↓
Provider Response
      ↓
Nexus Response
```

Provider-specific types must not leak beyond the adapter.

---

# 56. Error Contract

All provider errors must be normalized.

Base exception:

```python
class NexusSDKError(Exception):
    pass
```

Recommended hierarchy:

```text
NexusSDKError
├── ConfigurationError
├── AuthenticationError
├── AuthorizationError
├── ValidationError
├── ProviderError
│   ├── ProviderUnavailableError
│   ├── ProviderTimeoutError
│   ├── ProviderRateLimitError
│   └── ProviderResponseError
├── ModelError
├── RetrievalError
├── EmbeddingError
├── ToolError
├── AgentError
├── MemoryError
├── MCPError
└── CancellationError
```

Errors should include machine-readable codes.

```python
@dataclass
class ErrorInfo:
    code: str
    message: str
    retryable: bool = False
    provider: str | None = None
    request_id: str | None = None
```

Do not expose raw provider exceptions to API consumers.

---

# 57. Retry Policy

Retries must be centralized.

Retry only when the operation is safe and the error is retryable.

Usually retryable:

- transient network failures
- provider 5xx
- rate limits
- temporary service unavailable

Usually non-retryable:

- invalid request
- authentication failure
- authorization failure
- invalid tool arguments
- malformed model response

Use exponential backoff with jitter.

Do not allow unbounded retries.

---

# 58. Timeout Policy

Every external operation should have a timeout.

Required timeout boundaries:

- LLM request
- embedding request
- retrieval
- tool execution
- MCP call
- agent execution

Timeouts must be configurable by policy.

Agent-level deadlines must propagate to child operations.

---

# 59. Usage and Cost

Providers should normalize usage.

```python
@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    estimated_cost: float | None = None

    currency: str = "USD"
```

Usage should be emitted for:

- model calls
- embeddings
- tool calls where applicable
- agent runs

Cost calculation should be separated from provider invocation.

---

# 60. Observability

Every SDK operation should support:

- request ID
- trace ID
- provider name
- model
- operation name
- latency
- status
- error code
- token usage
- estimated cost

Recommended OpenTelemetry integration:

```text
Agent Run
  ├── Retrieval
  ├── Model Call
  │     └── Provider Call
  ├── Tool Call
  └── MCP Call
```

Sensitive prompt and response content must not automatically be logged.

---

# 61. Security Requirements

SDK interfaces must enforce the security architecture defined by `docs/07-security.md`.

Important rules:

1. Provider credentials are never exposed to agents.
2. Provider credentials are never exposed to models.
3. Tools execute under explicit permissions.
4. MCP capabilities require explicit authorization.
5. Tenant/project context is trusted infrastructure state.
6. Model output is untrusted input.
7. Tool arguments require schema validation.
8. Retrieved content is untrusted input.
9. Prompt injection defenses must exist at execution boundaries.
10. Secrets must be redacted from logs.
11. Provider responses must not bypass authorization.
12. Cross-tenant retrieval must be impossible by default.

---

# 62. Prompt Injection Boundary

The SDK must treat the following as untrusted:

- user content
- retrieved documents
- web pages
- tool results
- MCP resources
- external API responses
- uploaded files

Model-generated instructions must never directly modify:

- permissions
- system configuration
- tenant context
- project context
- secret access
- tool allowlists

High-risk actions should require policy enforcement and, where configured, human approval.

---

# 63. Tool Authorization

Before every tool execution:

```text
Agent
 ↓
Tool requested
 ↓
Tool exists?
 ↓
Schema valid?
 ↓
Tenant allowed?
 ↓
Project allowed?
 ↓
Agent allowed?
 ↓
User allowed?
 ↓
Tool policy allowed?
 ↓
Execute
```

Authorization must occur outside the model.

The model may request a tool, but it cannot authorize itself.

---

# 64. Structured Output

Providers should support normalized structured output.

```python
@dataclass(frozen=True)
class ResponseFormat:
    type: str
    schema: dict[str, Any] | None = None
```

Provider adapters must translate this to the provider's native structured-output mechanism.

The SDK must validate the returned structure before returning it to application code.

---

# 65. Model Capabilities

Models should expose normalized capabilities.

```python
@dataclass(frozen=True)
class ModelInfo:
    provider: str
    model: str

    context_window: int | None = None

    supports_tools: bool = False
    supports_streaming: bool = False
    supports_vision: bool = False
    supports_structured_output: bool = False
    supports_reasoning: bool = False
```

The router should use capabilities instead of provider-specific conditionals.

---

# 66. Configuration

Provider configuration must come from secure configuration management.

Example conceptual configuration:

```yaml
providers:
  llm:
    default: primary

    primary:
      provider: openai
      model: <configured-model>

  embeddings:
    default: primary
```

Secrets must come from:

- environment-backed secret stores
- cloud secret managers
- Vault
- equivalent secure infrastructure

Never commit API keys to source control.

---

# 67. Testing Requirements

Every interface must have contract tests.

For example:

```text
LLMProvider Contract Tests
├── completion
├── streaming
├── tool calls
├── structured output
├── timeout
├── cancellation
├── rate limit
├── provider error
└── usage reporting
```

Every provider adapter must pass the same contract suite.

This ensures:

```text
OpenAI Adapter
Anthropic Adapter
Google Adapter
Local Adapter
```

all behave consistently from the application's perspective.

---

# 68. Fake Providers

The SDK must provide fake/in-memory implementations for tests.

Examples:

```python
FakeLLMProvider
FakeEmbeddingProvider
FakeRetrievalProvider
FakeMemoryProvider
FakeTool
FakeMCPProvider
```

Tests must not require real external provider APIs.

---

# 69. Deterministic Testing

Agent tests should support deterministic model responses.

Example:

```python
fake_llm = FakeLLMProvider(
    responses=[
        CompletionResponse(...)
    ]
)
```

This allows testing:

- tool orchestration
- retry behavior
- authorization
- memory
- retrieval
- agent state transitions

without external model calls.

---

# 70. API Stability

Public SDK interfaces must be treated as stable contracts.

Breaking changes require:

1. versioning
2. migration notes
3. compatibility review
4. updates to contract tests
5. updates to all provider adapters

Avoid exposing provider-specific types in public interfaces.

---

# 71. Versioning

Recommended:

```text
nexus.sdk.v1
```

or package-level semantic versioning.

Breaking changes require a major version.

Non-breaking additions should prefer backwards-compatible optional fields.

---

# 72. Anti-Patterns

## 49.1 Direct vendor calls

Do not:

```python
from openai import AsyncOpenAI
```

inside application business logic.

---

## 49.2 Vendor response leakage

Do not return:

```python
openai.types.ChatCompletion
```

from Nexus interfaces.

Return:

```python
CompletionResponse
```

instead.

---

## 49.3 Model-controlled permissions

Never allow:

```text
Model → "give me admin tool"
```

to change actual permissions.

---

## 49.4 Unvalidated tool arguments

Never execute raw model-generated arguments without schema validation.

---

## 49.5 Unbounded agent loops

Agents must have configurable limits:

- maximum iterations
- maximum tool calls
- maximum execution time
- maximum token budget
- maximum cost budget

---

# 73. Agent Execution Limits

Recommended request-level controls:

```python
@dataclass(frozen=True)
class ExecutionLimits:
    max_iterations: int = 20
    max_tool_calls: int = 50
    timeout_ms: int = 120_000

    max_input_tokens: int | None = None
    max_output_tokens: int | None = None

    max_cost: float | None = None
```

Limits must be enforced by runtime infrastructure, not by model instructions.

---

# 74. Reference Runtime Flow

A typical request:

```text
HTTP Request
    ↓
FastAPI
    ↓
Authentication
    ↓
Authorization
    ↓
RequestContext
    ↓
Agent
    ↓
MemoryProvider
    ↓
RetrievalProvider
    ↓
ModelRouter
    ↓
LLMProvider
    ↓
Tool Authorization
    ↓
Tool / MCP Provider
    ↓
LLMProvider
    ↓
Agent Response
    ↓
Audit + Usage + Observability
    ↓
HTTP Response
```

---

# 75. Dependency Direction

The dependency graph must flow inward toward stable abstractions.

```text
API
 ↓
Application Services
 ↓
Agent Runtime
 ↓
SDK Interfaces
 ↓
Provider Adapters
 ↓
External Services
```

External providers must never become dependencies of core domain models.

---

# 76. Interface Ownership

| Interface | Responsibility |
|---|---|
| `LLMProvider` | Model execution |
| `ModelRouter` | Model/provider selection |
| `RetrievalProvider` | Knowledge retrieval |
| `EmbeddingProvider` | Vector generation |
| `Tool` | Executable capability |
| `Agent` | AI orchestration |
| `MemoryProvider` | Persistent memory |
| `MCPProvider` | MCP capability boundary |

---

# 77. Required Implementation Order

Implementation should proceed in this order:

1. Core types
2. Error types
3. Request context
4. LLMProvider
5. EmbeddingProvider
6. RetrievalProvider
7. Tool
8. MemoryProvider
9. MCPProvider
10. ModelRouter
11. Agent
12. Provider registry
13. Fake providers
14. Contract tests
15. First production provider adapter
16. Observability
17. Security enforcement
18. Runtime integration

---

# 78. Definition of Done

`docs/05-api-sdk.md` is considered implemented when:

- [ ] All eight required interfaces exist.
- [ ] Interfaces use vendor-neutral types.
- [ ] Async APIs are supported.
- [ ] Streaming is normalized.
- [ ] Cancellation is supported.
- [ ] Errors are normalized.
- [ ] Retry/timeout policies exist.
- [ ] Usage is normalized.
- [ ] Model capabilities are normalized.
- [ ] Provider registry exists.
- [ ] Dependency injection is implemented.
- [ ] Fake providers exist.
- [ ] Contract tests exist.
- [ ] Provider-specific types do not leak.
- [ ] Tool authorization occurs outside the model.
- [ ] MCP authorization is enforced.
- [ ] Tenant/project context is enforced.
- [ ] Observability hooks exist.
- [ ] Sensitive content is protected from accidental logging.
- [ ] Agent execution limits are enforced.
- [ ] SDK interfaces can be used without importing a vendor SDK.

---

# 79. Canonical Rule

The most important architectural rule is:

> **Nexus application code depends on Nexus interfaces; only provider adapters depend on external AI vendors.**

Therefore:

```text
                    ┌─────────────────┐
                    │ Nexus API       │
                    └────────┬────────┘
                             ↓
                    ┌─────────────────┐
                    │ Agent Runtime   │
                    └────────┬────────┘
                             ↓
                 ┌───────────────────────┐
                 │ Nexus SDK Interfaces │
                 └───────────┬───────────┘
                             ↓
          ┌──────────────────┼──────────────────┐
          ↓                  ↓                  ↓
    LLM Provider       Retrieval Provider   Tool/MCP
          ↓
   Vendor Adapters
          ↓
 ┌────────┼────────┬──────────┐
 ↓        ↓        ↓          ↓
OpenAI Anthropic Google     Local
```

This boundary is mandatory for Nexus and must be preserved as the system grows.

# REST API Contract

## 80. Implemented API Boundary

The Nexus REST API is the external application boundary for web clients, SDK clients, integrations, and other trusted consumers.

The configured default API prefix is:

```text
/api/v1
```

The REST layer depends on application services and provider-independent ports. Routes do not instantiate database or vendor AI clients directly.

The implemented Conversation flow is:

```text
Client
  ↓
HTTP /api/v1
  ↓
Authentication
  ↓
Conversation controller
  ↓
Conversation application service
  ↓
ConversationPersistence / LLMGateway
  ↓
SQLAlchemy persistence / LiteLLM adapter
```

The REST API must enforce the security requirements defined by `docs/07-security.md`.

---

## 81. Implemented Conversation Endpoints

The current Conversation API surface is:

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/conversations` | List Conversations created by the authenticated user |
| GET | `/api/v1/conversations/{conversation_public_id}/messages` | List persisted Messages for an authorized Conversation |
| POST | `/api/v1/conversations` | Create a standalone Conversation |
| POST | `/api/v1/conversations/{conversation_public_id}/messages` | Persist a user Message and stream the generated response as SSE |

There is no implemented Conversation detail, separate `/stream`, model-list, file, or project endpoint. Those remain future targets.

---

## 82. Implemented Authentication Boundary

Every protected endpoint requires authentication.

Canonical request header:

```http
Authorization: Bearer <access_token>
```

The authentication layer is responsible for validating the token and constructing trusted identity context.

Authentication must establish, where available:

```text
user_public_id
organization_public_id
session_public_id
```

Clients cannot supply or override these trusted values through Conversation request JSON.

Unauthenticated requests must fail before application execution.

Unauthenticated requests use:

```http
401 Unauthorized
```

Authorization failures must use:

```http
403 Forbidden
```

Provider credentials and API keys used by Nexus itself must never be accepted as conversation request fields.

---

## 83. Future Target: Shared Request Context

Nexus has request-ID middleware and a trusted authentication context, but it does not currently expose the speculative SDK-wide `RequestContext` described by earlier designs. Any future shared context must preserve trusted organization, user, permission, and correlation values without accepting client assertions as authority.

---

## 84. API Conventions

### 84.1 Content Type

JSON endpoints use:

```http
Content-Type: application/json
```

File upload is a future target and is expected to use:

```http
Content-Type: multipart/form-data
```

### 84.2 Identifiers

Resource IDs are opaque strings. Clients must not rely on their internal representation.

### 84.3 Timestamp convention

Conversation listing and persisted message-history timestamps are serialized as
RFC 3339 / ISO 8601 UTC timestamps. Future timestamp-bearing endpoints must
follow the same convention.

Example:

```text
2026-09-09T10:30:00Z
```

### 84.4 Request IDs

`RequestContextMiddleware` accepts an optional:

```http
X-Request-ID: <client-request-id>
```

Nexus preserves a valid caller-provided request ID and generates a new one when the header is absent or invalid. The middleware binds the value to the logging/request context and structured logging context, stores it in ASGI request state as `request.state.request_id`, and returns it in every response as:

```http
X-Request-ID: <request-id>
```

The existing logging `RequestContext` carries request-scoped logging metadata; it is not the future shared SDK `RequestContext` described in section 83. Propagating the request ID into a future shared SDK context remains future behavior.

### 84.5 Message submission deduplication

The implemented Conversation message endpoint accepts an optional UUID:

```http
Idempotency-Key: <uuid>
```

Reusing a key for the same Conversation provides at-most-once submission: it
does not create another Message or Generation and does not invoke the model
provider again. The duplicate request returns `409 Conflict`; Nexus does not
replay or resume the original SSE stream. The same key may be reused for a
different Conversation because deduplication is scoped by organization and
Conversation.

Supporting idempotency for other future durable operations remains a target.

---

## 85. Future Target: Pagination

The implemented Conversation list endpoint is intentionally unpaginated. Cursor-based pagination remains the target contract for a future phase.

Request:

```http
GET /api/v1/conversations?limit=20&cursor=<cursor>
```

Rules:

- `limit` is optional.
- The server enforces a maximum page size.
- `cursor` is opaque.
- Clients must not construct or interpret cursor internals.

Example response:

```json
{
  "data": [],
  "next_cursor": "opaque-cursor",
  "has_more": true
}
```

Pagination metadata must not leak resources outside the caller's authorization scope.

---

# 86. Implemented Conversation API

## 86.1 Create Conversation

```http
POST /api/v1/conversations
```

Request:

```json
{
  "title": "Customer support"
}
```

`title` is optional, trimmed by the API/application boundary, and limited to 255 characters. The authenticated organization and user are authoritative; they are not accepted in the request body. Current creation produces a standalone Conversation with no workspace or project scope.

Response:

```http
201 Created
```

```json
{
  "public_id": "4a1af83b-7b67-4bc0-8d40-e312629474b9",
  "organization_public_id": "e1355285-6fca-4c8c-b9b4-ff40a0a89959",
  "created_by_user_public_id": "356010a7-9941-4562-a7de-5d4a8ffad247",
  "workspace_public_id": null,
  "project_public_id": null,
  "title": "Customer support"
}
```

The API never accepts a caller-supplied organization or user ID as authority for tenancy or ownership.

---

## 86.2 List Conversations

```http
GET /api/v1/conversations
```

The authenticated organization and user determine the complete listing scope.
The endpoint accepts no organization or user identifiers from the client and
returns Conversations newest first.

Response:

```http
200 OK
```

```json
{
  "items": [
    {
      "public_id": "4a1af83b-7b67-4bc0-8d40-e312629474b9",
      "title": "Customer support",
      "created_at": "2026-09-09T10:30:00Z",
      "updated_at": "2026-09-09T10:30:00Z"
    }
  ]
}
```

When no Conversations exist, `items` is an empty array. Pagination, search, and
Conversation detail retrieval are not implemented by this endpoint.

---

# 87. Implemented Message API

## 87.1 Get Conversation Message History

```http
GET /api/v1/conversations/{conversation_public_id}/messages
```

The endpoint returns persisted Messages for an authorized standalone
Conversation in chronological order. Organization and user identity come only
from the trusted authentication context; clients cannot provide or override
them.

An unknown Conversation, a Conversation outside the authenticated organization,
and another user's standalone Conversation all return the same safe `404 Not
Found` response. Workspace- and project-scoped Conversations return `403
Forbidden` until their authorization model is implemented.

Response:

```http
200 OK
```

```json
{
  "items": [
    {
      "public_id": "c64542f2-d0ec-4d9d-9df0-a16259f340c6",
      "role": "user",
      "content": "Summarize this conversation.",
      "created_at": "2026-09-09T10:31:00Z"
    }
  ]
}
```

Only `public_id`, `role`, `content`, and `created_at` are exposed. When the
Conversation has no persisted Messages, `items` is an empty array.

---

## 87.2 Add Message and Stream Generation

```http
POST /api/v1/conversations/{conversation_public_id}/messages
```

Optional header:

```http
Idempotency-Key: 4a1af83b-7b67-4bc0-8d40-e312629474b9
```

Request:

```json
{
  "content": "Summarize this conversation.",
  "model": "gpt-4o-mini"
}
```

Both fields are required and must be non-blank. Extra fields are rejected. The model must be present in the configured `ModelPolicy` allowlist. The server controls message roles and trusted instructions.

Response:

```http
200 OK
```

```text
SSE stream described in section 88
```

If the Conversation already has a `RUNNING` Generation, Nexus returns a safe
`409 Conflict` before invoking the provider. A duplicate `Idempotency-Key` for
that Conversation also returns `409 Conflict`, even after the original
Generation has completed, failed, or been cancelled. These conflicts never
persist the losing request's Message or Generation.

---

# 88. Implemented Conversation SSE Contract

## 88.1 Stream establishment

`POST /api/v1/conversations/{conversation_public_id}/messages` preflights the provider and then returns Server-Sent Events. There is no separate `/stream` route.

Response:

```http
200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
```

Canonical event structure:

```text
event: <event_type>
data: <JSON>
```

Provider events are mapped to Conversation events; provider-specific events and payloads are never exposed.

Successful public event sequence:

```text
generation.started
message.delta
generation.usage       # when usage is available
generation.completed
```

Implemented event payloads are:

```text
event: generation.started
data: {"conversation_id":"<uuid>","generation_id":"<uuid>","model":"gpt-4o-mini"}

event: message.delta
data: {"conversation_id":"<uuid>","generation_id":"<uuid>","delta":"Here is "}

event: generation.usage
data: {"generation_id":"<uuid>","input_tokens":10,"output_tokens":5,"total_tokens":15}

event: generation.completed
data: {"conversation_id":"<uuid>","generation_id":"<uuid>","assistant_message_id":"<uuid>","finish_reason":"stop"}

event: generation.error
data: {"generation_id":"<uuid>","kind":"<stable-kind>","message":"The generation could not be completed."}
```

For a normally consumed stream, `generation.completed` or `generation.error` is terminal. A disconnected/cancelled consumer may not receive an SSE terminal event, but the server still resolves the persisted Generation lifecycle.

Errors occurring before the stream is established use the normal safe HTTP error contract. Errors after streaming begins are represented by `generation.error` only when the corresponding `FAILED` database transition succeeds. A terminal transition that loses a race is not emitted as if it won.

The API does not expose raw provider errors, private chain-of-thought, or internal reasoning.

---

# Future REST API Targets

Sections 89–102 describe future model, file, project, common-envelope, and broader API targets unless explicitly marked as implemented. They are not current routes or behavior.

# 89. Model API

## 89.1 List Models

```http
GET /v1/models
```

Response:

```http
200 OK
```

```json
{
  "data": [
    {
      "id": "model-id",
      "provider": "provider-name",
      "context_window": 128000,
      "supports_tools": true,
      "supports_streaming": true,
      "supports_vision": true,
      "supports_structured_output": true,
      "supports_reasoning": true
    }
  ]
}
```

The endpoint must return only models available under the caller's tenant, project, data-residency, privacy, and policy constraints.

Provider credentials and internal configuration must never be returned.

---

# 90. File API

## 90.1 Upload File

```http
POST /v1/files
```

Request:

```http
Content-Type: multipart/form-data
```

Form fields:

```text
file=<binary>
project_id=<optional-project-id>
metadata=<optional-json>
```

Response:

```http
201 Created
```

```json
{
  "id": "file_123",
  "filename": "requirements.pdf",
  "content_type": "application/pdf",
  "size_bytes": 123456,
  "project_id": "project_123",
  "status": "uploaded",
  "created_at": "2026-09-09T10:30:00Z"
}
```

File uploads must be subject to:

- authentication
- authorization
- tenant isolation
- project isolation
- file-size limits
- allowed MIME/type policy
- malware/content scanning where configured
- storage policy
- audit logging

Uploaded content is untrusted input and must not automatically become trusted instructions.

---

# 91. Project API

## 91.1 Create Project

```http
POST /v1/projects
```

Request:

```json
{
  "name": "Nexus Project",
  "description": "Project description",
  "metadata": {}
}
```

Response:

```http
201 Created
```

```json
{
  "id": "project_123",
  "name": "Nexus Project",
  "description": "Project description",
  "created_at": "2026-09-09T10:30:00Z",
  "updated_at": "2026-09-09T10:30:00Z",
  "metadata": {}
}
```

The tenant is derived from authenticated identity. A request must not be able to create a project under another tenant.

---

# 92. Common Response Envelope

Resource endpoints may return the resource directly.

Collection endpoints use:

```json
{
  "data": [],
  "next_cursor": null,
  "has_more": false
}
```

The API must remain consistent across all collection endpoints.

---

# 93. API Error Contract

All non-streaming API errors use:

```json
{
  "error": {
    "code": "machine_readable_code",
    "message": "Human-readable message",
    "request_id": "req_123",
    "retryable": false
  }
}
```

Optional fields:

```json
{
  "error": {
    "code": "provider_rate_limited",
    "message": "The model provider is temporarily rate limited.",
    "request_id": "req_123",
    "retryable": true,
    "details": {},
    "provider": "provider-name"
  }
}
```

Do not return:

- stack traces
- raw provider exceptions
- credentials
- secrets
- internal database details
- private authorization policy details
- hidden prompts
- internal chain-of-thought

Recommended HTTP mappings:

| HTTP status | Meaning |
|---|---|
| 400 | Invalid request |
| 401 | Authentication required/invalid |
| 403 | Authenticated but not authorized |
| 404 | Resource not available to caller |
| 409 | Conflict |
| 413 | Payload/file too large |
| 422 | Validation failure |
| 429 | Rate limited |
| 500 | Internal server error |
| 502 | Upstream provider failure |
| 503 | Service temporarily unavailable |
| 504 | Upstream timeout |

The exact error `code` is the stable machine-readable contract; clients should not parse the human-readable `message`.

---

# 94. Validation Contract

Request validation must occur before application execution.

Validate:

- required fields
- field types
- string lengths
- enum values
- numeric bounds
- pagination limits
- file constraints
- message content constraints
- model identifiers
- project/conversation ownership

Pydantic models should be used at the FastAPI boundary where runtime validation is required.

Validation errors must use the common error contract.

---

# 95. Authorization Contract

Authentication identifies the caller. Authorization determines what the caller may do.

Before accessing a conversation:

```text
Authenticated User
      ↓
Tenant membership
      ↓
Project membership
      ↓
Conversation ownership/access
      ↓
Operation permission
```

Before model execution:

```text
User
 ↓
Tenant policy
 ↓
Project policy
 ↓
Model policy
 ↓
Data residency/privacy policy
 ↓
ModelRouter
 ↓
Provider
```

Before tools/MCP:

```text
User
 ↓
Tenant
 ↓
Project
 ↓
Agent
 ↓
Tool/MCP permission
 ↓
Schema validation
 ↓
Execution
```

The model must never be the authorization authority.

---

# 96. Rate Limiting

The API must support policy-driven rate limiting.

Limits may apply at:

```text
IP
User
Tenant
Project
Endpoint
Model
Provider
```

Rate-limit responses should use:

```http
429 Too Many Requests
```

Where appropriate, include:

```http
Retry-After: <seconds>
```

Rate-limit state must not allow one tenant to consume another tenant's quota.

---

# 97. API Security Requirements

The REST API must preserve the security boundaries defined by the SDK and `docs/07-security.md`.

Required rules:

1. Authentication occurs before protected application operations.
2. Authorization occurs before resource access.
3. Tenant identity comes from trusted authentication context.
4. Project access is validated against the tenant.
5. Conversation access is validated against the user/project policy.
6. Model selection cannot bypass policy.
7. Tool execution cannot be authorized by model output.
8. MCP operations require explicit authorization.
9. Uploaded files are untrusted content.
10. Retrieved content is untrusted content.
11. Secrets never appear in ordinary API responses or logs.
12. Provider-specific objects never leak through public API models.
13. Internal reasoning must not be exposed by default.
14. Cross-tenant resource access must fail closed.
15. API errors must not disclose sensitive implementation details.

---

# 98. OpenAPI Contract

FastAPI should generate an OpenAPI specification from the canonical request/response models.

The generated OpenAPI document must be treated as an implementation artifact of this contract, not as permission to silently change the API.

API changes require:

1. contract review
2. request/response model updates
3. OpenAPI update
4. API contract tests
5. SDK/client compatibility review
6. security review for affected endpoints

Breaking changes require API versioning or an approved migration strategy.

---

# 99. API Contract Tests

Every endpoint must have contract tests covering:

```text
Authentication
Authorization
Validation
Successful response
Error response
Tenant isolation
Project isolation
Pagination
Idempotency where applicable
Request IDs
Rate limiting where applicable
Provider failure
Timeouts
Streaming lifecycle
Streaming errors
Cancellation where supported
```

Streaming tests must verify:

```text
started
  ↓
zero or more deltas/events
  ↓
completed OR error
  ↓
connection closes
```

Contract tests must verify that provider-specific response types never cross the API boundary.

---

# 100. API + SDK Boundary

The REST API and Python SDK are separate contracts.

The API defines the external HTTP boundary:

```text
HTTP
JSON
SSE
Authentication
HTTP status codes
API resource models
```

The SDK defines the internal Python capability boundary:

```text
Protocols
Python types
Async interfaces
Provider adapters
Agent runtime
Tools
Retrieval
Memory
MCP
```

They may share conceptual/domain types, but neither layer should expose implementation-specific types from the other.

Canonical dependency:

```text
External Client
      ↓
REST API Contract
      ↓
Application Services
      ↓
Agent Runtime
      ↓
Python SDK Contracts
      ↓
Provider Adapters
      ↓
External Providers
```

The REST API must not call vendor SDKs directly.

---

# 101. API Definition of Done

The REST API portion of `docs/05-api-sdk.md` is complete when:

- [ ] All eight initial endpoints are defined.
- [ ] Request models are defined.
- [ ] Response models are defined.
- [ ] Authentication expectations are defined.
- [ ] Authorization expectations are defined.
- [ ] Tenant/project isolation is defined.
- [ ] Error format and HTTP status mappings are defined.
- [ ] Pagination is defined.
- [ ] Request IDs are defined.
- [ ] Idempotency expectations are defined.
- [ ] Streaming/SSE behavior is defined.
- [ ] Streaming terminal/error behavior is defined.
- [ ] File upload constraints are defined.
- [ ] Model visibility rules are defined.
- [ ] Rate limiting expectations are defined.
- [ ] OpenAPI generation is defined.
- [ ] API contract tests are required.
- [ ] REST and SDK boundaries are explicitly separated.
- [ ] Vendor-specific types do not cross the public API boundary.
- [ ] Security requirements align with `docs/07-security.md`.

---

# 102. Canonical API Rule

The REST API is a stable external contract, while the Python SDK is the stable internal capability contract.

Neither should expose provider-specific implementation details.

```text
                    ┌────────────────────┐
                    │ External Clients   │
                    └─────────┬──────────┘
                              ↓
                    ┌────────────────────┐
                    │ REST API /v1       │
                    └─────────┬──────────┘
                              ↓
                    ┌────────────────────┐
                    │ Application Layer  │
                    └─────────┬──────────┘
                              ↓
                    ┌────────────────────┐
                    │ Agent Runtime      │
                    └─────────┬──────────┘
                              ↓
                    ┌────────────────────┐
                    │ Nexus SDK          │
                    │ Interfaces         │
                    └─────────┬──────────┘
                              ↓
                 ┌────────────┼────────────┐
                 ↓            ↓            ↓
              LLM         Retrieval     Tool/MCP
                 ↓            ↓            ↓
             Adapters / Implementations
```

This separation is mandatory for maintainability, security, provider neutrality, and API stability.
