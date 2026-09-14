# NEXUS — Domain Map

**Status:** Canonical AI navigation and ownership map

## Purpose

This file tells AI agents **where to go** in the repository. It is a routing map, not a complete technical specification.

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
│   ├── security/        # security boundary and security services
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
    ├── unit/
    ├── components/
    ├── integration/
    └── e2e/
```

Frontend does not mirror backend layers.

## Domain Routing Table

| Domain | Backend ownership | Frontend ownership | Tests | Primary concern |
|---|---|---|---|---|
| Authentication | `backend/src/nexus/security/` and authentication-specific application/domain code | `frontend/src/features/authentication/` | `backend/tests/` + `frontend/tests/` | identity, sessions, credentials, tokens |
| Authorization | `backend/src/nexus/security/` and authorization-specific application/domain code | `frontend/src/features/authorization/` | `backend/tests/` + `frontend/tests/` | permissions and access decisions |
| Tenants | `backend/src/nexus/` tenant domain | `frontend/src/features/tenants/` | domain-focused tests | tenant lifecycle and isolation |
| Projects | `backend/src/nexus/` project domain | `frontend/src/features/projects/` | domain-focused tests | project lifecycle and ownership |
| Conversations | `backend/src/nexus/` conversation domain | `frontend/src/features/conversations/` | domain-focused tests | conversations and messages |
| Models | `backend/src/nexus/` model domain | `frontend/src/features/models/` | domain-focused tests | providers and model selection |
| Agents | `backend/src/nexus/` agent domain | `frontend/src/features/agents/` | domain-focused tests | agent execution and runs |
| Workflows | `backend/src/nexus/` workflow domain | `frontend/src/features/workflows/` | domain-focused tests | workflow definitions and execution |
| Tools | `backend/src/nexus/` tool domain | `frontend/src/features/tools/` | domain-focused tests | tool registration and execution |
| MCP | `backend/src/nexus/` MCP domain | `frontend/src/features/mcp/` when needed | domain-focused tests | MCP integration |
| Memory | `backend/src/nexus/` memory domain | `frontend/src/features/memory/` when needed | domain-focused tests | memory lifecycle and retrieval |
| Retrieval / RAG | `backend/src/nexus/` retrieval domain | `frontend/src/features/retrieval/` when needed | domain-focused tests | indexing, search, embeddings, ranking |
| Files | `backend/src/nexus/` file domain | `frontend/src/features/files/` | domain-focused tests | uploads, metadata, storage, access |
| Streaming | `backend/src/nexus/` streaming domain | feature-specific streaming UI | domain-focused tests | event delivery and stream lifecycle |
| Observability | `backend/src/nexus/logging/` and observability code | frontend error reporting only where explicitly required | separate backend/frontend tests | operational visibility |
| Configuration | `backend/src/nexus/config/` | frontend application configuration | focused tests | runtime configuration |
| Audit | `backend/src/nexus/` audit domain | feature-specific admin UI when needed | domain-focused tests | security/admin audit history |

The table describes ownership, not a requirement to create every domain immediately.

## Domain Investigation Rule

If a task concerns Authorization:

```text
Authorization
  ↓
relevant authorization docs
  ↓
backend authorization code
frontend authorization code
  ↓
authorization tests
```

Do NOT inspect Retrieval, Models, MCP, Agents, Memory, or Workflows unless a real dependency requires it.

If a dependency is required:

```text
Primary domain
  ↓
prove dependency
  ↓
inspect only that dependency
  ↓
return to primary domain
```

Do not recursively load all related domains.

## Cross-Domain Expansion Is Allowed Only When

- the Jira task explicitly identifies the dependency;
- the approved implementation plan identifies it;
- domain documentation delegates the behavior to it;
- source imports/calls it for the behavior under investigation;
- tests demonstrate that it participates in the failing path;
- an API, data, security, or architecture contract requires it.

If another domain must be **modified** and the approved task does not cover that change, stop and request specification/human approval.

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
2. Define backend ownership.
3. Define frontend ownership when applicable.
4. Define tests.
5. Add domain documentation when implementation begins.

Keep this file navigational. It should answer:

> **Where do I go?**

not:

> **Tell me everything about the domain.**
