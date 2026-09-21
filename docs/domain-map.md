# NEXUS — Domain Map

**Status:** Canonical AI navigation and ownership map

## Purpose

This file tells human developers and AI agents exactly where each NEXUS capability belongs. It is an operational routing and ownership map, not a complete technical specification.

The rule is:

> **Start narrow. Expand only when evidence requires it.**

## Mandatory Routing

For every implementation task:

```text
Jira task
  ↓
AGENTS.md / INVARIANTS.md / engineering principles
  ↓
docs/domain-map.md
  ↓
Primary domain
  ↓
Relevant domain documentation
  ↓
Relevant source
  ↓
Relevant tests
  ↓
Dependencies only when actually required
```

Agents MUST NOT inspect every domain by default.

## Repository Ownership

### Backend

```text
backend/
├── src/nexus/
│   ├── api/             # HTTP/FastAPI transport
│   ├── application/     # use cases and orchestration
│   ├── domain/          # business rules and contracts
│   ├── infrastructure/  # external systems and adapters
│   ├── security/        # authentication, authorization, security context/primitives
│   ├── config/          # application configuration
│   ├── errors/          # framework-independent NEXUS errors
│   ├── logging/         # request/context logging support
│   ├── events/          # event contracts/publishing
│   └── main.py          # application entrypoint
└── tests/
    ├── unit/
    ├── api/
    ├── integration/
    └── fixtures/
```

Backend tests are independent from frontend tests.

Backend tests are organized first by test boundary, then by NEXUS domain when
there are enough tests to justify a domain folder:

```text
backend/tests/unit/knowledge/
backend/tests/api/knowledge/
backend/tests/integration/knowledge/
```

Do not create empty domain test folders before tests exist. Each domain owns the
unit, API, and integration tests that verify its behavior and contracts.

### Frontend

```text
frontend/
├── src/
│   ├── app/             # application shell/bootstrap
│   ├── features/        # feature/domain-owned UI and behavior
│   ├── components/      # genuinely shared UI
│   ├── pages/           # route-level composition
│   ├── services/        # shared API/service layer
│   ├── hooks/           # shared hooks
│   ├── stores/          # shared client state
│   ├── types/           # shared TypeScript types
│   └── lib/             # small shared utilities/integrations
└── tests/
    └── e2e/
```

Frontend does not mirror backend layers. Unit and component tests stay
colocated with the source they verify under `frontend/src/**/*.test.ts` and
`frontend/src/**/*.test.tsx`. Playwright E2E tests live under
`frontend/tests/e2e/`.

## Global Cross-Domain Rule

An AI agent may inspect another domain only when at least one of these conditions is true:

1. the Jira task explicitly identifies the dependency;
2. the approved implementation plan identifies it;
3. this domain map identifies it as an allowed dependency required for the task;
4. an existing import, API, data, or security contract proves it;
5. a failing test proves that the other domain participates in the behavior.

Shared/platform infrastructure may be inspected when required by an identified dependency. Unrelated product domains MUST NOT be inspected or modified.

If another domain must be **modified** and the approved task does not cover that change, stop and request specification/human approval.

## Domain Ownership Map

Each domain entry defines purpose, ownership, tests, documentation, dependencies, explicitly unrelated areas, and when cross-domain inspection is permitted.

### Authentication

- **Purpose:** Establish and verify user identity, sessions, credentials, and authentication tokens.
- **Backend ownership:** the feature-first `backend/src/nexus/authentication/` package, with concrete provider and persistence adapters under `backend/src/nexus/infrastructure/` and object construction under `backend/src/nexus/composition/`.
- **Frontend ownership:** `frontend/src/features/authentication/`.
- **Tests:** Authentication-focused backend unit/API/integration tests and frontend authentication unit/component/integration/E2E tests.
- **Documentation:** `docs/07-security.md` plus `docs/domains/authentication/` when domain-specific documentation exists.
- **Shared dependencies:** configuration, canonical errors, logging, shared security primitives.
- **Allowed dependencies:** Users; Organizations when tenant/organization context is required; Authorization for post-authentication access decisions.
- **Explicitly unrelated domains:** Knowledge/RAG, Models, Agents, MCP, Memory, Workflows, Artifacts unless an approved task proves a dependency.
- **Cross-domain inspection conditions:** Only under the Global Cross-Domain Rule; authentication work does not justify broad inspection of downstream product domains.

### Authorization

- **Purpose:** Make access decisions for authenticated principals and enforce permissions.
- **Backend ownership:** `backend/src/nexus/security/authorization/`, `backend/src/nexus/application/authorization/`, `backend/src/nexus/domain/authorization/`, and relevant API routes/dependencies.
- **Frontend ownership:** `frontend/src/features/authorization/`.
- **Tests:** Authorization-focused backend unit/API/integration tests and frontend authorization tests.
- **Documentation:** `docs/07-security.md` plus `docs/domains/authorization/` when present.
- **Shared dependencies:** security context/primitives, canonical errors, logging, configuration.
- **Allowed dependencies:** Authentication, Users, Organizations, Projects.
- **Explicitly unrelated domains:** Knowledge/RAG, Models, Agents, MCP, Memory, Workflows unless an approved task proves a dependency.
- **Cross-domain inspection conditions:** Only when a task, plan, existing contract, or failing test proves the dependency; otherwise remain inside Authorization.

### Users

- **Purpose:** Own user profile, lifecycle, identity-adjacent user data, and user-level business concepts that are not authentication mechanics.
- **Backend ownership:** user-specific application/domain/API code under `backend/src/nexus/`.
- **Frontend ownership:** `frontend/src/features/users/` when user-facing functionality exists.
- **Tests:** User-focused backend unit/API/integration tests and frontend user tests.
- **Documentation:** `docs/domains/users/` when implementation begins; security-sensitive behavior also consults `docs/07-security.md`.
- **Shared dependencies:** configuration, errors, logging, persistence adapters as required.
- **Allowed dependencies:** Authentication, Authorization, Organizations, Projects where contracts require them.
- **Explicitly unrelated domains:** Models, Agents, MCP, Memory, Workflows, Knowledge/RAG unless the task proves a direct relationship.
- **Cross-domain inspection conditions:** Only under the Global Cross-Domain Rule.

### Organizations

- **Purpose:** Own organization lifecycle, membership, organizational boundaries, and organization-level tenancy semantics.
- **Backend ownership:** organization-specific application/domain/API code under `backend/src/nexus/`.
- **Frontend ownership:** `frontend/src/features/organizations/`.
- **Tests:** Organization-focused backend unit/API/integration tests and frontend organization tests.
- **Documentation:** `docs/domains/organizations/` when implementation begins; relevant security and data docs where required.
- **Shared dependencies:** persistence, configuration, errors, logging.
- **Allowed dependencies:** Users, Authentication, Authorization, Projects.
- **Explicitly unrelated domains:** Models, Agents, MCP, Memory, Workflows, Knowledge/RAG unless the task proves a dependency.
- **Cross-domain inspection conditions:** Only under the Global Cross-Domain Rule.

### Projects

- **Purpose:** Own project lifecycle, ownership, membership/context, and project-scoped business state.
- **Backend ownership:** project-specific application/domain/API code under `backend/src/nexus/`.
- **Frontend ownership:** `frontend/src/features/projects/`.
- **Tests:** Project-focused backend and frontend tests.
- **Documentation:** `docs/domains/projects/` when implementation begins; `docs/06-data-model.md` for persistence changes.
- **Shared dependencies:** persistence, configuration, errors, logging.
- **Allowed dependencies:** Users, Organizations, Authorization; product domains may reference project identity when their contracts are project-scoped.
- **Explicitly unrelated domains:** Any product domain not explicitly participating in the current project-related contract.
- **Cross-domain inspection conditions:** Only under the Global Cross-Domain Rule.

### Conversations

- **Purpose:** Own conversation lifecycle, conversation state, participants/context, and conversation-level orchestration boundaries.
- **Backend ownership:** conversation-specific application/domain/API code under `backend/src/nexus/`.
- **Frontend ownership:** `frontend/src/features/conversations/`.
- **Tests:** Conversation-focused backend and frontend tests.
- **Documentation:** `docs/domains/conversations/` when implementation begins; API/data docs when contracts change.
- **Shared dependencies:** Projects when project-scoped, persistence, errors, logging, events where required.
- **Allowed dependencies:** Messages, Models, Streaming/Runs, Authorization when contracts require them.
- **Explicitly unrelated domains:** Files, Knowledge/RAG, Agents, MCP, Memory, Workflows unless an approved conversation feature explicitly depends on them.
- **Cross-domain inspection conditions:** Only under the Global Cross-Domain Rule.

### Messages

- **Purpose:** Own message entities, message lifecycle, roles/content metadata, and message-level persistence/contracts.
- **Backend ownership:** message-specific application/domain/API code under `backend/src/nexus/`.
- **Frontend ownership:** message UI owned by `frontend/src/features/conversations/` unless a dedicated message feature is later justified.
- **Tests:** Message-focused tests colocated with conversation/message test areas.
- **Documentation:** `docs/domains/messages/` or conversation documentation when messages remain a conversation subdomain.
- **Shared dependencies:** persistence, errors, logging.
- **Allowed dependencies:** Conversations; Streaming/Runs for incremental output; Models when model-generated messages are involved.
- **Explicitly unrelated domains:** Organizations, Files, MCP, Workflows, Artifacts unless a proven contract requires them.
- **Cross-domain inspection conditions:** Only under the Global Cross-Domain Rule.

### Models

- **Purpose:** Own model/provider selection contracts and model capability metadata; provider implementations belong to infrastructure.
- **Backend ownership:** model-specific application/domain code under `backend/src/nexus/`; external provider adapters under `backend/src/nexus/infrastructure/`.
- **Frontend ownership:** `frontend/src/features/models/`.
- **Tests:** Model/provider contract unit/integration tests and frontend model-selection tests.
- **Documentation:** `docs/domains/models/` when implementation begins; API docs for exposed model contracts.
- **Shared dependencies:** configuration, errors, logging, infrastructure adapters.
- **Allowed dependencies:** Conversations or Agents only when those domains explicitly invoke model contracts.
- **Explicitly unrelated domains:** Authentication, Organizations, Files, Workflows, Artifacts unless a task proves a dependency.
- **Cross-domain inspection conditions:** Only under the Global Cross-Domain Rule; do not inspect consumers merely because they may eventually use models.

### Files

- **Purpose:** Own file upload lifecycle, metadata, storage contracts, and file access behavior.
- **Backend ownership:** file-specific application/domain/API code under `backend/src/nexus/`; storage adapters under `backend/src/nexus/infrastructure/`.
- **Frontend ownership:** `frontend/src/features/files/`.
- **Tests:** File-focused unit/API/integration tests and frontend file tests.
- **Documentation:** `docs/domains/files/` when implementation begins; `docs/05-api-sdk.md`, `docs/06-data-model.md`, and `docs/07-security.md` when applicable.
- **Shared dependencies:** persistence/storage adapters, authorization, errors, logging, configuration.
- **Allowed dependencies:** Projects or Organizations for ownership scope; Knowledge/RAG when ingestion explicitly consumes files.
- **Explicitly unrelated domains:** Models, Agents, MCP, Memory, Workflows unless an approved feature proves the relationship.
- **Cross-domain inspection conditions:** Only under the Global Cross-Domain Rule.

### Knowledge / RAG

- **Purpose:** Own ingestion, indexing, chunking, embeddings, retrieval, ranking, and knowledge-query contracts.
- **Backend ownership:** knowledge/retrieval-specific application/domain code under `backend/src/nexus/`; vector stores, embedding providers, and external retrieval adapters under `backend/src/nexus/infrastructure/`.
- **Frontend ownership:** `frontend/src/features/knowledge/`.
- **Tests:** Knowledge/RAG unit/API/integration tests and frontend knowledge tests.
- **Documentation:** `docs/domains/knowledge/` when implementation begins; data/API/security docs where contracts require them.
- **Shared dependencies:** Files when file ingestion is used, persistence, infrastructure adapters, configuration, errors, logging.
- **Allowed dependencies:** Files; Models only for embedding/reranking contracts where explicitly required; Projects/Authorization when knowledge is scoped.
- **Explicitly unrelated domains:** Agents, MCP, Memory, Workflows, Artifacts unless the task explicitly integrates them.
- **Cross-domain inspection conditions:** Only under the Global Cross-Domain Rule.

### Agents

- **Purpose:** Own agent definitions, orchestration contracts, execution policy, and agent-specific lifecycle.
- **Backend ownership:** agent-specific application/domain/API code under `backend/src/nexus/`; provider/tool adapters under infrastructure where appropriate.
- **Frontend ownership:** `frontend/src/features/agents/`.
- **Tests:** Agent-focused unit/API/integration tests and frontend agent tests.
- **Documentation:** `docs/domains/agents/` when implementation begins.
- **Shared dependencies:** errors, logging, configuration, events/runs as required.
- **Allowed dependencies:** Models, MCP, Memory, Tools/integrations, Workflows, Streaming/Runs only when the agent contract explicitly uses them.
- **Explicitly unrelated domains:** Users, Organizations, Files, Knowledge/RAG unless the current agent feature proves a dependency.
- **Cross-domain inspection conditions:** Only under the Global Cross-Domain Rule; future capability adjacency is not sufficient evidence.

### MCP

- **Purpose:** Own Model Context Protocol integration contracts, MCP server/client connectivity, capability discovery, and MCP-specific execution boundaries.
- **Backend ownership:** MCP-specific application/domain code under `backend/src/nexus/`; network/provider adapters under infrastructure.
- **Frontend ownership:** `frontend/src/features/mcp/` when MCP configuration or visibility is exposed to users.
- **Tests:** MCP-focused backend tests and frontend MCP tests when applicable.
- **Documentation:** `docs/domains/mcp/` when implementation begins.
- **Shared dependencies:** configuration, security, errors, logging, infrastructure adapters.
- **Allowed dependencies:** Agents or Tools only when an approved contract integrates MCP with them.
- **Explicitly unrelated domains:** Authentication, Organizations, Projects, Knowledge/RAG, Memory, Workflows unless proven by the task.
- **Cross-domain inspection conditions:** Only under the Global Cross-Domain Rule.

### Memory

- **Purpose:** Own durable/ephemeral memory concepts, storage/retrieval contracts, lifecycle, and memory policy.
- **Backend ownership:** memory-specific application/domain/API code under `backend/src/nexus/`; persistence adapters under infrastructure.
- **Frontend ownership:** `frontend/src/features/memory/` when user-visible memory controls exist.
- **Tests:** Memory-focused backend tests and frontend memory tests when applicable.
- **Documentation:** `docs/domains/memory/` when implementation begins; data/security docs as required.
- **Shared dependencies:** persistence, configuration, errors, logging.
- **Allowed dependencies:** Agents or Conversations only when those consumers explicitly invoke memory contracts.
- **Explicitly unrelated domains:** Files, MCP, Workflows, Artifacts, Organizations unless proven by the task.
- **Cross-domain inspection conditions:** Only under the Global Cross-Domain Rule.

### Workflows

- **Purpose:** Own workflow definitions, steps, lifecycle, orchestration, and execution state.
- **Backend ownership:** workflow-specific application/domain/API code under `backend/src/nexus/`.
- **Frontend ownership:** `frontend/src/features/workflows/`.
- **Tests:** Workflow-focused backend and frontend tests.
- **Documentation:** `docs/domains/workflows/` when implementation begins.
- **Shared dependencies:** persistence, events, errors, logging, configuration, Streaming/Runs where execution is asynchronous or streamed.
- **Allowed dependencies:** Agents, MCP, Models, Files, or other domains only when workflow step contracts explicitly reference them.
- **Explicitly unrelated domains:** Any domain not used by the workflow contract under test or implementation.
- **Cross-domain inspection conditions:** Only under the Global Cross-Domain Rule.

### Artifacts

- **Purpose:** Own generated artifact metadata, lifecycle, persistence references, and artifact access contracts.
- **Backend ownership:** artifact-specific application/domain/API code under `backend/src/nexus/`; storage adapters under infrastructure.
- **Frontend ownership:** `frontend/src/features/artifacts/` when artifact browsing or interaction exists.
- **Tests:** Artifact-focused backend and frontend tests.
- **Documentation:** `docs/domains/artifacts/` when implementation begins; data/API/security docs as required.
- **Shared dependencies:** storage/persistence, authorization, errors, logging.
- **Allowed dependencies:** Conversations, Agents, Workflows, or Files only when they explicitly create, consume, or expose artifact contracts.
- **Explicitly unrelated domains:** MCP, Memory, Knowledge/RAG, Organizations unless proven by the task.
- **Cross-domain inspection conditions:** Only under the Global Cross-Domain Rule.

### Streaming / Runs

- **Purpose:** Own run lifecycle and streaming/event-delivery contracts for long-running or incremental operations.
- **Backend ownership:** run/streaming-specific application/domain/API code under `backend/src/nexus/`; event publisher abstractions under `backend/src/nexus/events/` and transport adapters under infrastructure where required.
- **Frontend ownership:** feature-specific streaming/run UI, with genuinely shared client streaming support under shared frontend service/lib areas only when reusable.
- **Tests:** Streaming/run backend unit/API/integration tests and relevant frontend integration/E2E tests.
- **Documentation:** `docs/domains/streaming/` or `docs/domains/runs/` when implementation begins; `docs/05-api-sdk.md` for public streaming contracts.
- **Shared dependencies:** events, errors, logging, configuration.
- **Allowed dependencies:** Conversations, Agents, Workflows, Models only when those domains produce or consume run/stream contracts.
- **Explicitly unrelated domains:** Organizations, Files, Knowledge/RAG, MCP, Memory unless a specific run contract proves involvement.
- **Cross-domain inspection conditions:** Only under the Global Cross-Domain Rule.

### Observability

- **Purpose:** Own server-side operational visibility, logging context, metrics/tracing contracts when introduced, and diagnostics boundaries.
- **Backend ownership:** `backend/src/nexus/logging/` and approved observability code under platform/shared infrastructure.
- **Frontend ownership:** frontend error reporting/diagnostics only where explicitly required; do not mirror backend observability architecture.
- **Tests:** Focused backend logging/observability tests and frontend diagnostics tests when applicable.
- **Documentation:** platform/operations documentation plus `docs/08-engineering-principles.md` where relevant.
- **Shared dependencies:** configuration, errors, request context, infrastructure integrations when approved.
- **Allowed dependencies:** May observe any domain through stable logging/telemetry contracts but must not take ownership of domain business logic.
- **Explicitly unrelated domains:** No product domain business implementation belongs here.
- **Cross-domain inspection conditions:** Inspect a product domain only when diagnosing an identified logging/telemetry path or when a task explicitly names that domain.

### Platform / Shared Infrastructure

- **Purpose:** Own reusable technical capabilities that serve multiple domains without owning their business rules.
- **Backend ownership:** `backend/src/nexus/infrastructure/`, `backend/src/nexus/config/`, `backend/src/nexus/errors/`, `backend/src/nexus/logging/`, `backend/src/nexus/events/`, application bootstrap in `backend/src/nexus/main.py`, and approved shared API plumbing.
- **Frontend ownership:** `frontend/src/app/`, genuinely shared `components/`, `services/`, `hooks/`, `stores/`, `types/`, and `lib/` code that is not product-domain specific.
- **Tests:** Shared backend/frontend unit/integration tests appropriate to the shared capability.
- **Documentation:** `docs/04-architecture.md`, `docs/08-engineering-principles.md`, this domain map, and focused platform docs when needed.
- **Shared dependencies:** By definition provides shared technical contracts; dependencies must point toward stable infrastructure abstractions rather than absorb product-domain behavior.
- **Allowed dependencies:** Domain contracts only where infrastructure implements an explicit interface or adapter required by that domain.
- **Explicitly unrelated domains:** Product business rules from Authentication, Authorization, Users, Organizations, Projects, Conversations, Messages, Models, Files, Knowledge/RAG, Agents, MCP, Memory, Workflows, or Artifacts.
- **Cross-domain inspection conditions:** May inspect a product domain only to satisfy an explicit adapter/configuration/API contract proven by the task, plan, import, test, or documented dependency.

## Additional Existing/Navigational Areas

The repository may also contain navigational areas such as configuration, audit, tools/integrations, or tenant terminology. These do not replace the required domains above. If such an area becomes a first-class product domain, update this map with the same ownership fields and cross-domain restrictions.

## Global Documentation Routing

Use only when relevant:

| Concern | Document |
|---|---|
| Project scope | `docs/00-project-plan.md` |
| Requirements | `docs/03-system-requirements.md` |
| Architecture | `docs/04-architecture.md` |
| REST/streaming/SDK contracts | `docs/05-api-sdk.md` |
| Data model | `docs/06-data-model.md` |
| Security | `docs/07-security.md` |
| Engineering rules | `docs/08-engineering-principles.md` |
| Domain routing | `docs/domain-map.md` |

Security-sensitive work MUST additionally consult `docs/07-security.md`.
Persistence changes MUST additionally consult `docs/06-data-model.md`.
API changes MUST additionally consult `docs/05-api-sdk.md`.

## Error and Logging Ownership

Backend operational errors and server-side logging belong to the backend platform.

```text
Backend
├── errors/   → canonical NEXUS error contract
└── logging/  → request/context/server logging
```

The frontend MUST still implement client-side error handling and user-facing error states, but it does not duplicate the backend error/logging platform.

Frontend MUST NOT log secrets, tokens, credentials, or sensitive request/response content.

## Domain Documentation

When a domain is ready for implementation, its detailed documentation MAY live under:

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

Create only files that are useful. `README.md` should be the AI entry point.

## Local Agent Instructions

A domain may contain:

```text
backend/src/nexus/<domain>/AGENTS.md
```

or an equivalent local instruction file when genuinely necessary.

Local instructions may tighten but must not weaken root rules.

## Maintenance

When a new major domain is introduced:

1. Add it to this map.
2. Define its purpose.
3. Define backend ownership.
4. Define frontend ownership when applicable.
5. Define test ownership.
6. Define documentation ownership.
7. Define shared and allowed dependencies.
8. Define explicitly unrelated domains.
9. Define cross-domain inspection conditions.

Keep this file operational and navigational. It should answer:

> **Where do I go, what may I inspect, and what must I avoid?**
