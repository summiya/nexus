# Nexus AI — Domain Map

**File:** `docs/domain-map.md`  
**Status:** Canonical AI navigation and routing map  
**Purpose:** Tell AI agents where to go without requiring them to read the entire repository.

---

# 1. How to Use This Map

The domain map is a **router**, not a complete technical specification.

An AI agent MUST use this file after reading:

1. `AGENTS.md`
2. `INVARIANTS.md`
3. `docs/08-engineering-principles.md`

Then identify the smallest relevant domain.

The normal path is:

```text
Issue / Task
    ↓
domain-map.md
    ↓
Owning domain
    ↓
Domain documentation
    ↓
Domain source
    ↓
Domain tests
```

The agent MUST NOT read every domain's documentation by default.

---

# 2. Domain Model

A Nexus domain normally has three connected parts:

```text
Domain
├── Documentation
├── Source
└── Tests
```

Example:

```text
Authentication
├── docs/domains/authentication/
├── src/nexus/auth/
└── tests/auth/
```

These are three views of the same bounded area:

- Documentation = what the domain is supposed to do.
- Source = how it is implemented.
- Tests = evidence that it works.

---

# 3. Routing Table

| Domain | Typical Problems / Behaviors | Documentation | Source | Tests | Related Domains | Dependency Reason |
|---|---|---|---|---|---|---|
| Authentication | login, logout, sessions, credentials, tokens, identity verification | `docs/domains/authentication/` | `src/nexus/auth/` | `tests/auth/` | Tenants, Authorization | identity/scope and access decisions |
| Authorization | permissions, roles, policies, access decisions | `docs/domains/authorization/` | `src/nexus/authorization/` | `tests/authorization/` | Authentication, Tenants, Projects | authenticated identity and resource scope |
| Tenants | tenant lifecycle, tenant scope, isolation | `docs/domains/tenants/` | `src/nexus/tenants/` | `tests/tenants/` | Authentication, Projects, Authorization | ownership and tenant-scoped access |
| Projects | project lifecycle, project scope, ownership | `docs/domains/projects/` | `src/nexus/projects/` | `tests/projects/` | Tenants, Authorization, Conversations | project ownership and access |
| Conversations | conversations, messages, participants, conversation state | `docs/domains/conversations/` | `src/nexus/conversations/` | `tests/conversations/` | Projects, Agents, Streaming, Files | conversation scope, execution, transport, attachments |
| Models | LLM providers, model configuration, model selection | `docs/domains/models/` | `src/nexus/models/` | `tests/models/` | Agents, Configuration | model selection and runtime configuration |
| Agent Runtime | agent lifecycle, execution, context, tool invocation, runs | `docs/domains/agents/` | `src/nexus/agents/` | `tests/agents/` | Models, Tools, Memory, Authorization, Streaming | model execution, capabilities, context, permissions, output delivery |
| Workflows | workflow definitions, steps, orchestration, execution | `docs/domains/workflows/` | `src/nexus/workflows/` | `tests/workflows/` | Agents, Tools, Authorization | workflow execution and controlled capabilities |
| Tools | tool registration, invocation, permissions, execution | `docs/domains/tools/` | `src/nexus/tools/` | `tests/tools/` | Authorization, MCP, Agents | permission checks, MCP integration, agent execution |
| MCP | MCP clients, servers, resources, permissions, protocol integration | `docs/domains/mcp/` | `src/nexus/mcp/` | `tests/mcp/` | Authentication, Authorization, Tools | server/client identity, permissions, tool/resource integration |
| Memory | short/long-term memory, storage, retrieval of memories | `docs/domains/memory/` | `src/nexus/memory/` | `tests/memory/` | Agents, Retrieval, Tenants, Projects | agent context, search, and scoped persistence |
| Retrieval | RAG, indexing, search, embeddings, retrieval pipelines | `docs/domains/retrieval/` | `src/nexus/retrieval/` | `tests/retrieval/` | Memory, Files, Models, Tenants, Projects | indexed content, embeddings, model use, and data scope |
| Files | upload, storage, metadata, file lifecycle, access | `docs/domains/files/` | `src/nexus/files/` | `tests/files/` | Projects, Conversations, Retrieval, Authorization | ownership, attachments, indexing, and access |
| Streaming | streaming responses, events, transport, stream lifecycle | `docs/domains/streaming/` | `src/nexus/streaming/` | `tests/streaming/` | Conversations, Agents, Workflows | delivery of execution and conversation events |
| Observability | logs, metrics, traces, correlation, instrumentation | `docs/domains/observability/` | `src/nexus/observability/` | `tests/observability/` | All domains as applicable | instrumentation and operational visibility |
| Configuration | application configuration, environment, feature configuration | `docs/domains/configuration/` | `src/nexus/config/` | `tests/configuration/` | All domains as applicable | runtime configuration |
| Audit | audit events, security records, compliance history | `docs/domains/audit/` | `src/nexus/audit/` | `tests/audit/` | Authentication, Authorization, Tenants, Projects, MCP, Tools | security-sensitive and ownership-sensitive events |

## Dependency Routing Rule

The **Related Domains** column describes potential dependency paths. It does **not** mean the agent must read every listed domain.

Agents MUST use dependency relationships as **routing hints**:

```text
Task
  ↓
Owning domain
  ↓
Investigate source/docs/tests
  ↓
Dependency actually relevant?
  ├── NO  → stay within current scope
  └── YES → follow the relevant dependency
```

Agents MUST NOT recursively load every related domain.

A dependency should be followed when:

- the task explicitly names the dependency;
- the relevant domain documentation says the behavior is delegated to that dependency;
- source code calls or imports the dependency for the behavior being investigated;
- tests demonstrate that the dependency is part of the failing path;
- an API, data, security, or architecture contract requires the dependency.

### Example: MCP Authentication

For:

> "MCP server authentication is failing."

Start with:

```text
MCP
├── docs/domains/mcp/
├── src/nexus/mcp/
└── tests/mcp/
```

If investigation shows that MCP authentication delegates to Nexus Authentication:

```text
MCP
  ↓
Authentication
```

Then load only the relevant Authentication context:

```text
docs/domains/authentication/
src/nexus/auth/
tests/auth/
```

If the investigation then shows that authorization is also involved:

```text
MCP
  ↓
Authentication
  ↓
Authorization
```

Load the relevant Authorization context as well.

Do **not** automatically load Workflows, Retrieval, Memory, Conversations, or other unrelated domains.

### Example: MCP Tool Permission

For:

> "An MCP tool can execute without the required permission."

The likely routing path is:

```text
MCP
  ↓
Authorization
  ↓
Tools
```

The agent should confirm the actual dependency from documentation/source/tests before expanding.

### Example: MCP Display Bug

For:

> "The MCP tool description is displayed incorrectly."

The agent may only need:

```text
MCP
  ↓
src/nexus/mcp/
  ↓
tests/mcp/
```

There is no reason to load Authentication or Authorization unless investigation shows that they participate in the failing behavior.

---

# 4. Global Documentation Routing

Not every task belongs to one domain.

Use the global specifications when the task concerns:

| Concern | Primary Document |
|---|---|
| Project roadmap / delivery | `docs/00-project-plan.md` |
| System requirements | `docs/01-system-requirements.md` |
| Overall architecture | `docs/02-architecture.md` |
| REST / streaming API | `docs/03-api-contract.md` |
| Python SDK | `docs/04-python-sdk.md` |
| Agent execution architecture | `docs/05-agent-runtime.md` |
| PostgreSQL / persistence / schema | `docs/06-data-model.md` |
| Security | `docs/07-security.md` |
| Engineering / implementation rules | `docs/08-engineering-principles.md` |
| Architectural rationale | `docs/decisions/` |

Global documents SHOULD be loaded only when relevant, except for the small mandatory documents specified in `AGENTS.md`.

---

# 5. Security Routing

Security-sensitive work MUST additionally consult:

```text
docs/07-security.md
```

Examples:

```text
Authentication
    → authentication domain docs
    → security.md

Authorization
    → authorization domain docs
    → security.md

Tenant isolation
    → tenants domain docs
    → data model
    → security.md

MCP permissions
    → MCP domain docs
    → tools/authorization docs as needed
    → security.md
```

Do not assume that reading only a domain document is sufficient for security-sensitive changes.

---

# 6. Data Routing

For persistence-related changes:

```text
Domain documentation
        ↓
docs/06-data-model.md
        ↓
Relevant source
        ↓
Migration(s)
        ↓
Relevant tests
```

Database changes MUST remain consistent with the canonical data model.

---

# 7. API Routing

For API changes:

```text
Owning domain
        ↓
docs/03-api-contract.md
        ↓
Domain API documentation
        ↓
API source
        ↓
API tests
```

If the Python SDK is affected:

```text
docs/04-python-sdk.md
```

must also be considered.

---

# 8. Agent / Workflow Routing

For agent execution:

```text
Agent Runtime
    → docs/domains/agents/
    → src/nexus/agents/
    → tests/agents/
    → docs/05-agent-runtime.md
```

For workflows:

```text
Workflows
    → docs/domains/workflows/
    → src/nexus/workflows/
    → tests/workflows/
```

If workflows execute agents or tools, expand into those domains only when the implementation actually crosses those boundaries.

---

# 9. Cross-Domain Routing

Some features naturally cross domains.

For example:

```text
"User sends a message and an agent executes a tool."
```

Possible path:

```text
Conversations
    ↓
Agent Runtime
    ↓
Tools
    ↓
Authorization
```

The agent SHOULD start with the domain that owns the reported behavior and expand only along the actual dependency path.

Do not read all four domains automatically.

---

# 10. Domain Documentation Structure

When a domain is being defined, its documentation MAY contain:

```text
docs/domains/<domain>/
├── README.md
├── requirements.md
├── architecture.md
├── flows.md
├── api.md
├── data.md
├── security.md
├── testing.md
└── debugging.md
```

These files are created only when useful.

Do not create empty documentation files merely to satisfy a template.

---

# 11. Local Source Instructions

A domain MAY have:

```text
src/nexus/<domain>/AGENTS.md
```

This file contains only rules that are genuinely local to that source tree.

It is not a duplicate of the root `AGENTS.md`.

Nested instructions inherit and tighten the root rules.

---

# 12. Example: Authentication

For:

> "Refresh tokens are not invalidated after logout."

The agent should follow:

```text
AGENTS.md
    ↓
INVARIANTS.md
    ↓
docs/08-engineering-principles.md
    ↓
docs/domain-map.md
    ↓
Authentication
    ↓
docs/domains/authentication/
    ├── README.md
    ├── requirements.md
    ├── architecture.md
    ├── flows.md
    ├── api.md
    └── security.md
    ↓
src/nexus/auth/
    └── AGENTS.md   (if present)
    ↓
Relevant source files
    ↓
tests/auth/
    ↓
Implement + test
```

It does NOT need to read:

```text
docs/domains/mcp/
docs/domains/workflows/
docs/domains/retrieval/
src/nexus/mcp/
src/nexus/workflows/
...
```

unless the investigation proves they are involved.

---

# 13. Example: MCP Permission Bug

For:

> "An MCP tool can be executed without the required permission."

Route:

```text
AGENTS.md
    ↓
INVARIANTS.md
    ↓
08-engineering-principles.md
    ↓
domain-map.md
    ↓
MCP
    ↓
docs/domains/mcp/
    ↓
src/nexus/mcp/
    ↓
tests/mcp/
    ↓
Authorization / Tools only if the dependency requires it
    ↓
docs/07-security.md
```

---

# 14. Example: Database Schema Change

For:

> "Add a project-level setting to the database."

Route:

```text
AGENTS.md
    ↓
INVARIANTS.md
    ↓
08-engineering-principles.md
    ↓
domain-map.md
    ↓
Projects
    ↓
docs/domains/projects/
    ↓
docs/06-data-model.md
    ↓
src/nexus/projects/
    ↓
migrations/
    ↓
tests/projects/
```

---

# 15. Routing Principle

The domain map follows one rule:

> **Start narrow. Expand only when evidence requires it.**

The agent should never treat the repository as one undifferentiated context window.

The preferred investigation path is:

```text
Global rules
    ↓
Map
    ↓
Domain
    ↓
Local documentation
    ↓
Source
    ↓
Tests
    ↓
Dependencies only when needed
```

---

# 16. Ownership Rule

When unsure where new behavior belongs, determine:

1. Which domain owns the business rule?
2. Which domain owns the data?
3. Which domain owns the public behavior?
4. Which domain should be responsible for testing it?

Prefer one clear owner over duplicated responsibility.

If ownership is genuinely ambiguous and affects architecture, consult the relevant architecture documentation and ADRs before inventing a new boundary.

---

# 17. Maintenance Rule

Whenever a new major Nexus domain is introduced:

1. Add it to this map.
2. Define its source location.
3. Define its test location.
4. Create domain documentation when the domain is ready to be implemented.
5. Add local `AGENTS.md` only if genuinely necessary.

The domain map itself MUST remain concise and navigational.

It should answer:

> **"Where do I go?"**

not:

> **"Tell me everything about this domain."**
