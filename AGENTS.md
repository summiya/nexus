# Nexus AI — Agent Instructions

**File:** `AGENTS.md`  
**Status:** Mandatory  
**Audience:** AI coding agents working on Nexus

## 1. Mission

Nexus is an AI platform built with Python and FastAPI.

AI agents must implement, test, debug, and maintain Nexus according to the documented requirements, architecture, security rules, API contracts, data model, and engineering principles.

**Follow the existing Nexus design before inventing a new design.**

## 2. Mandatory Reading Before EVERY Task

Before making ANY code change, the agent MUST:

1. Read this `AGENTS.md`.
2. Read `docs/08-engineering-principles.md`.
3. Understand the task and acceptance criteria.
4. Identify the affected domain/module.
5. Read the relevant domain documentation.
6. Check applicable global specifications.
7. Inspect the existing implementation.
8. Inspect relevant tests.
9. Only then modify code.

This applies to:
- New features
- Bug fixes
- Refactoring
- Performance work
- Security changes
- API changes
- Database changes
- Tests
- Configuration changes
- Infrastructure changes

**MUST NOT:** Begin implementation before completing the required reading.

## 3. Global Nexus Specifications

| Document | Purpose |
|---|---|
| `docs/00-project-plan.md` | Project goals, milestones, and scope |
| `docs/01-system-requirements.md` | System requirements |
| `docs/02-architecture.md` | Global architecture |
| `docs/03-api-contract.md` | REST and streaming API contracts |
| `docs/04-python-sdk.md` | Python SDK interfaces |
| `docs/05-agent-runtime.md` | Agent runtime architecture |
| `docs/06-data-model.md` | Database and persistence model |
| `docs/07-security.md` | Security requirements |
| `docs/08-engineering-principles.md` | Engineering rules and coding principles |

### Reading Rule

Always read:
- `AGENTS.md`
- `docs/08-engineering-principles.md`

Then read only the global specifications relevant to the task.

Do not deeply read every document for every task.

## 4. Domain Routing

Before changing code, identify the domain responsible for the behavior.

Consult:

`docs/domain-map.md`

Start investigation in the owning domain.

### Example

For:

> Access token validation is failing.

Start with:

`docs/domains/authentication/`  
`src/nexus/auth/`  
`tests/auth/`

Do not begin by reading unrelated LLM, Agent, MCP, Workflow, or Retrieval documentation unless evidence shows they are involved.

## 5. Local-First Investigation

Default workflow:

```text
Task
 ↓
Identify domain
 ↓
Read domain documentation
 ↓
Inspect domain source
 ↓
Inspect domain tests
 ↓
Reproduce problem
 ↓
Investigate dependencies only when necessary
 ↓
Implement smallest safe change
 ↓
Run tests
```

**MUST:** Start locally.

**MUST NOT:** Explore the entire repository without a reason.

**MAY:** Expand investigation when a dependency, cross-domain interface, failing test, documented architectural dependency, or explicit issue scope requires it.

## 6. Planned Nexus Domains

These are intended architectural boundaries.

### Identity & Authentication
Purpose: login/logout, access tokens, refresh tokens, API keys, sessions, authentication middleware.

Code: `src/nexus/auth/`  
Docs: `docs/domains/authentication/`

### Authorization
Purpose: RBAC, permissions, tenant/project/resource authorization, tool authorization, MCP authorization.

Code: `src/nexus/authorization/`  
Docs: `docs/domains/authorization/`

### Tenants
Purpose: tenant management, configuration, boundaries, tenant-level resources.

Code: `src/nexus/tenants/`  
Docs: `docs/domains/tenants/`

### Projects
Purpose: project management, configuration, resources, project-level isolation.

Code: `src/nexus/projects/`  
Docs: `docs/domains/projects/`

### Conversations
Purpose: conversations, messages, state, lifecycle.

Code: `src/nexus/conversations/`  
Docs: `docs/domains/conversations/`

### Models / LLM Providers
Purpose: model registry, provider adapters, model routing/configuration, streaming responses, provider failures/retries.

Code: `src/nexus/models/`  
Docs: `docs/domains/models/`

### Agent Runtime
Purpose: agent execution/lifecycle, planning, tool selection, context assembly, state, execution loops.

Code: `src/nexus/agents/`  
Docs: `docs/domains/agents/`

### Workflows
Purpose: workflow definitions/execution, steps, state, orchestration, retries/failures.

Code: `src/nexus/workflows/`  
Docs: `docs/domains/workflows/`

### Tools
Purpose: tool definitions/registration/execution, permissions, validation, results.

Code: `src/nexus/tools/`  
Docs: `docs/domains/tools/`

### MCP
Purpose: MCP server connections, tools, resources, authentication, permissions, lifecycle.

Code: `src/nexus/mcp/`  
Docs: `docs/domains/mcp/`

### Memory
Purpose: conversation/long-term memory, storage, retrieval, lifecycle, permissions.

Code: `src/nexus/memory/`  
Docs: `docs/domains/memory/`

### Retrieval
Purpose: document retrieval, semantic/vector search, pipelines, chunking, embeddings, ranking.

Code: `src/nexus/retrieval/`  
Docs: `docs/domains/retrieval/`

### Files
Purpose: uploads, metadata, storage, processing, permissions, lifecycle.

Code: `src/nexus/files/`  
Docs: `docs/domains/files/`

### Streaming
Purpose: streaming responses/events, connection lifecycle, backpressure, streaming errors.

Code: `src/nexus/streaming/`  
Docs: `docs/domains/streaming/`

### Observability
Purpose: logging, metrics, tracing, health checks, diagnostics.

Code: `src/nexus/observability/`  
Docs: `docs/domains/observability/`

### Configuration
Purpose: application/environment/runtime configuration and feature configuration.

Code: `src/nexus/config/`  
Docs: `docs/domains/configuration/`

### Audit
Purpose: security/admin audit events, resource activity, compliance-related events.

Code: `src/nexus/audit/`  
Docs: `docs/domains/audit/`

## 7. Domain Ownership

Every domain must clearly define:

- Purpose
- Responsibilities
- Non-responsibilities
- Dependencies
- Consumers
- Source code
- Tests
- Documentation
- Security requirements

**MUST NOT:** Create overlapping ownership between domains.

Authentication answers:

> Who are you?

Authorization answers:

> Are you allowed to do this?

Keep these responsibilities separate.

## 8. Domain Documentation

Each implemented domain should eventually have:

```text
docs/domains/<domain>/
    README.md
    requirements.md
    architecture.md
    flows.md
    api.md
    data.md
    security.md
    testing.md
    debugging.md
```

Not every domain needs every file immediately.

`README.md` is the AI entry point and should identify scope, responsibilities, non-responsibilities, dependencies, consumers, source code, tests, and relevant specifications.

## 9. Domain AGENTS.md

Important domains may contain:

`src/nexus/<domain>/AGENTS.md`

Local instructions may be stricter than root instructions.

Local instructions MUST NOT weaken global security or architecture requirements.

## 10. Cross-Domain Changes

Cross-domain changes are allowed when technically necessary.

Before making one, identify:

1. Owning domain.
2. Dependent domain.
3. Reason for dependency.
4. Existing interface or contract.
5. Required documentation.
6. Required tests.

**MUST NOT:** Modify another domain simply because it is easier.

**SHOULD:** Use existing domain interfaces.

**MUST:** Update relevant documentation when a domain boundary or contract changes.

## 11. Architecture Changes

Treat these as significant architecture changes:

- New domain
- New service
- New database technology
- New infrastructure technology
- New public API pattern
- Major dependency change
- Domain boundary change
- Authentication model change
- Authorization model change
- Agent execution model change
- Workflow execution model change

**MUST NOT:** Silently introduce a major architectural change during a normal implementation task.

## 12. Existing Code Comes First

Before creating a new abstraction, service, class, or utility:

1. Search for an existing implementation.
2. Search for an existing interface.
3. Search for an existing pattern.
4. Reuse it if appropriate.

**MUST NOT:** Create duplicate functionality without justification.

## 13. Bug-Fixing Rules

When fixing a bug:

1. Identify the affected domain.
2. Read its documentation.
3. Reproduce the issue.
4. Identify the root cause.
5. Check relevant tests.
6. Make the smallest safe change.
7. Add/update regression tests.
8. Run relevant tests.
9. Check security and contract implications.
10. Update documentation if behavior or architecture changed.

**MUST NOT:**
- Fix symptoms while ignoring the root cause.
- Delete tests to make them pass.
- Weaken security controls.
- Perform unrelated refactoring.
- Change public behavior silently.

## 14. New Feature Rules

Before implementing a new feature:

1. Identify the owning domain.
2. Confirm the feature exists in the requirements.
3. Read the domain specification.
4. Check architecture implications.
5. Check API implications.
6. Check data-model implications.
7. Check security implications.
8. Implement.
9. Add tests.
10. Update documentation when necessary.

## 15. Dependencies

When adding a dependency:

### MUST
- Confirm it is necessary.
- Check whether an existing dependency already provides the capability.
- Ensure compatibility with the architecture.
- Update dependency configuration.
- Document significant architectural dependencies.

### MUST NOT
- Add libraries for trivial functionality.
- Add duplicate libraries serving the same purpose.
- Introduce infrastructure without a clear requirement.

## 16. Tests

### MUST
- Add tests for new behavior.
- Add regression tests for bug fixes.
- Preserve existing tests.
- Run relevant tests before completing the task.

### MUST NOT
- Delete failing tests merely to make the suite pass.
- Weaken assertions without justification.
- Skip security tests for convenience.

## 17. Documentation Changes

Documentation MUST be updated when a change affects:

- Requirements
- Architecture
- API contracts
- Data model
- Security requirements
- Domain boundaries
- Important operational behavior

Documentation does not need to change for every internal implementation detail.

## 18. Scope Control

### MUST
Prefer:

```text
small task
  ↓
small investigation
  ↓
small change
  ↓
focused tests
```

### MUST NOT
Turn a feature request into a repository-wide refactoring project.

If unrelated problems are discovered, report them rather than silently fixing them unless they block the assigned task.

## 19. Final Verification

Before declaring a task complete, verify:

- [ ] Requirements are satisfied.
- [ ] Engineering principles are followed.
- [ ] Architecture is preserved.
- [ ] Domain boundaries are preserved.
- [ ] Security requirements are satisfied.
- [ ] API contracts are preserved.
- [ ] Data integrity is preserved.
- [ ] Tests pass.
- [ ] New behavior has appropriate tests.
- [ ] Documentation is updated where required.
- [ ] No unrelated changes were introduced.

## 20. Golden Rule

> **Understand first. Scope locally. Follow the documented architecture. Make the smallest safe change. Test it. Expand only when evidence requires it.**
