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
| `docs/03-system-requirements.md` | System requirements |
| `docs/04-architecture.md` | Global architecture |
| `docs/05-api-sdk.md` | REST and streaming API contracts |
| `docs/05-api-sdk.md` | Python SDK interfaces |
| `docs/04-architecture.md` | Agent runtime architecture |
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

## 20. React + TypeScript Frontend Engineering Standard

The NEXUS frontend is **React + TypeScript**. All agents making frontend changes MUST follow this section in addition to the general engineering rules above.

### 20.1 Before Frontend Implementation

The agent MUST:

1. Read `AGENTS.md` and `docs/08-engineering-principles.md`.
2. Inspect the existing `frontend/` structure.
3. Inspect existing React components, routes, hooks, API clients/services, state management, styling/design-system components, utilities, and tests relevant to the task.
4. Reuse existing patterns and components before creating new ones.
5. Confirm the task's API and security contracts before implementing client behavior.

The agent MUST NOT introduce a new frontend library, framework, state-management solution, UI system, or data-fetching library unless the repository genuinely requires it and the change is justified.

### 20.2 React Architecture

- MUST use React + TypeScript; do not introduce Vue or another frontend framework.
- Components MUST have a clear and coherent responsibility.
- UI/presentation SHOULD be separated from business logic and API communication.
- Reusable behavior SHOULD live in appropriately scoped hooks or services.
- API calls SHOULD use the existing API client/service layer rather than being scattered through presentational components.
- Authentication/session handling MUST be centralized rather than reimplemented independently by pages.
- Frontend authorization checks are for UX only; the backend remains the authoritative security boundary.
- Prefer composition over deeply nested or monolithic components.
- Avoid giant page components containing layout, API calls, business logic, validation, and state management together.
- Do not split code into many files merely to appear architecturally clean; create boundaries when they improve ownership, reuse, testing, or readability.
- Preserve the existing frontend architecture unless a concrete requirement justifies changing it.

### 20.3 NEXUS Application Shell

The NEXUS authenticated application should be structured as a reusable application shell rather than a single monolithic dashboard component.

The shell should conceptually separate:

```text
App Shell
├── Sidebar / Primary Navigation
├── Header / Workspace Controls
├── Main Workspace
├── Composer / Contextual Actions
└── Account / Organization Menu
```

Major feature areas should remain independently maintainable:

```text
Chat
Projects
Artifacts
Knowledge
Tools
Agents
Workflows
Settings
```

The application shell owns shared layout and navigation. Each feature owns its page-level UI and behavior.

Familiar interaction patterns from products such as ChatGPT or Claude MAY be used as UX inspiration, but NEXUS MUST maintain its own branding, product identity, components, and implementation.

### 20.4 TypeScript

- MUST use strict TypeScript practices consistent with the repository configuration.
- MUST NOT use `any` unless there is a documented and unavoidable reason.
- API responses, component props, forms, and important domain objects MUST have explicit types.
- Frontend types MUST remain aligned with the backend API contract.
- MUST NOT use unsafe casts simply to suppress type errors.
- Prefer discriminated unions and narrow types when they make state or API behavior clearer.

### 20.5 State Management

- Keep state local when only one component or feature needs it.
- Use shared/global state only when multiple areas genuinely require the same state.
- Do not duplicate the same source of truth across components or stores.
- Keep server state conceptually separate from local UI state.
- Loading, success, empty, error, and unauthorized states MUST be handled explicitly where applicable.
- Avoid global state as a default solution for every problem.

### 20.6 Authentication and Session Security

- The React client MUST NOT be treated as a security authority.
- The client MUST NOT trust browser-supplied organization IDs, user IDs, roles, permissions, membership status, or ownership as proof of authorization.
- Long-lived refresh tokens MUST NOT be stored in `localStorage` or `sessionStorage`.
- Access credentials MUST use the approved ephemeral/runtime mechanism defined by the NEXUS authentication architecture.
- Authentication/session handling SHOULD be centralized through the existing client architecture.
- Session expiry and unauthorized responses MUST be handled consistently.
- The UI MAY hide or disable controls based on effective permissions for usability, but protected backend operations MUST still be enforced server-side.
- Secrets, OTPs, tokens, and sensitive authentication information MUST NOT be logged or embedded in client bundles.

### 20.7 API Integration

- MUST use the existing typed API client/service abstraction when one exists.
- MUST NOT scatter ad-hoc `fetch`/HTTP calls throughout components when an existing API layer is available.
- API contracts MUST be represented with appropriate TypeScript types.
- API errors MUST be handled consistently.
- UI components SHOULD not depend directly on backend implementation details.
- Client behavior MUST follow the documented REST/streaming API contracts.

### 20.8 Routing

- Authenticated routes MUST be protected through centralized session/authentication logic.
- Unauthenticated, loading, expired-session, and unauthorized route states MUST be handled intentionally.
- Navigation visibility MUST NOT be treated as an authorization mechanism.
- Route structure SHOULD reflect the product's domain/feature boundaries.

### 20.9 Components and Reuse

- Reuse existing components, primitives, and design-system patterns whenever appropriate.
- Components SHOULD remain readable and reasonably sized.
- Extract logic when a component becomes difficult to understand, reuse, or test.
- Avoid creating generic components whose only purpose is theoretical future reuse.
- Avoid duplicate versions of the same button, modal, form control, layout, or navigation pattern without a documented reason.
- Follow existing naming, folder, import, and component conventions.

### 20.10 Forms and User Input

- Forms MUST provide clear labels and validation feedback.
- Loading/submission states MUST be represented.
- Duplicate submissions SHOULD be prevented where appropriate.
- User-facing validation MUST NOT replace backend validation for security-sensitive rules.
- Authentication and organization-management forms MUST handle API errors without exposing internal implementation details.

### 20.11 UI/UX and Accessibility

- Reuse the established NEXUS design language and components.
- Interfaces SHOULD be responsive and usable across supported screen sizes.
- Use semantic HTML wherever appropriate.
- Interactive elements MUST be keyboard accessible.
- Focus states MUST remain visible and usable.
- Form controls MUST have accessible labels.
- Use ARIA only when semantic HTML does not provide the required meaning.
- Loading, error, empty, disabled, and success states SHOULD be visually and semantically clear.
- Do not copy proprietary branding, assets, or source code from other products.

### 20.12 Performance

- Avoid unnecessary renders and network requests.
- Do not add memoization, caching, virtualization, or other optimization purely speculatively.
- Use route-level or feature-level lazy loading where it provides a clear benefit and fits the existing architecture.
- Optimize after identifying an actual performance concern rather than complicating simple code prematurely.

### 20.13 Frontend Testing

For meaningful frontend behavior changes, the agent MUST add or update appropriate automated tests.

Tests SHOULD prioritize user-visible behavior and contracts over implementation details.

Where applicable, test:

- successful user flows;
- loading states;
- error states;
- empty states;
- validation;
- authentication/session transitions;
- permission-denied behavior;
- important navigation behavior;
- API integration boundaries.

The agent MUST NOT:

- delete tests to make the suite pass;
- weaken assertions without justification;
- replace meaningful tests with snapshots or implementation-detail assertions merely for convenience;
- claim a feature is complete without running the relevant tests.

Before completion, run the applicable:

- TypeScript/type checks;
- linting;
- frontend automated tests;
- production build.

### 20.14 Frontend Dependencies

Before adding a frontend dependency:

1. Search the repository for an existing solution.
2. Check whether the current React/tooling stack already provides the capability.
3. Confirm the dependency is required by the task.
4. Consider bundle size, maintenance, security, and compatibility.
5. Document or surface significant architectural dependency changes.

Do not add libraries for trivial helpers or duplicate an existing capability.

### 20.15 Frontend Scope Control

Frontend tasks MUST remain scoped to the assigned Jira issue.

If a task requires a backend/API change, the agent MUST identify it as a cross-domain dependency and follow the cross-domain rules rather than silently expanding the task.

If unrelated frontend problems are discovered, report them unless they directly block the assigned task.

### 20.16 Frontend Completion Checklist

Before declaring a frontend task complete, verify:

- [ ] React + TypeScript architecture is preserved.
- [ ] Existing components/patterns were inspected and reused where appropriate.
- [ ] No unnecessary frontend dependencies were added.
- [ ] Components have clear responsibilities.
- [ ] Business logic/API access is not unnecessarily embedded in presentational components.
- [ ] Authentication/session handling follows the approved security architecture.
- [ ] Backend authorization remains authoritative.
- [ ] Important loading/error/empty/unauthorized states are handled.
- [ ] Accessibility requirements are satisfied for changed UI.
- [ ] TypeScript checks pass.
- [ ] Linting passes.
- [ ] Relevant automated tests pass.
- [ ] Production build passes.
- [ ] No debug code or unrelated changes remain.

## 21. Source of Truth and Current Repository Reality

The current repository implementation is the primary source of truth for code structure, supported commands, and established patterns.

Older planning documents may describe intended or historical structures. Before following a path, abstraction, command, or architectural pattern from documentation, verify that it matches the current repository.

Current backend code and tests live under:

```text
backend/src/nexus/
backend/tests/
```

**MUST NOT:** Create missing folders, abstractions, services, or layers only because an older document describes them.

**MUST:** Reconcile task requirements with the actual current implementation before coding.

When documentation and current approved implementation differ, preserve the current approved implementation unless the task explicitly requires changing it.

## 22. Engineering Principles for Every Change

Apply these principles pragmatically to every task:

- SOLID
- KISS
- YAGNI
- DRY without premature abstraction
- Separation of Concerns
- Dependency Inversion
- Composition over Inheritance
- Explicit over Implicit
- Fail Fast
- Strong Typing
- Secure by Design
- Defense in Depth
- Least Privilege
- Tenant Isolation where applicable
- Data Integrity
- Testability
- Maintainability
- Scalability

SOLID does **not** mean creating more classes, interfaces, factories, or layers.

**MUST NOT** introduce abstractions such as generic repositories, base services, factories, registries, service locators, DI frameworks, Unit of Work frameworks, command buses, mediator layers, generic mappers, or similar patterns unless they solve a concrete current Nexus requirement.

Prefer the smallest architecture that keeps responsibilities and dependency boundaries clear.

## 23. Task and Phase Discipline

The user/task prompt defines the immediate scope. This file defines the default engineering workflow.

### Plan-only tasks

If the task says PLAN ONLY, DESIGN ONLY, REVIEW ONLY, or equivalent:

- inspect the repository;
- analyze the problem;
- return the plan/review;
- do not modify files;
- do not create a branch;
- do not commit;
- do not push;
- do not create a PR.

### Implementation tasks

When implementation is approved:

1. Verify the required prerequisite work is already on the intended base branch.
2. Sync the latest base branch, normally `main`.
3. Create or use the explicitly requested task/phase branch.
4. Implement only the approved task or phase.
5. Add/update tests.
6. Run focused validation while developing.
7. Run the repository-standard final validation.
8. Inspect the complete final diff.
9. Perform architecture, security, maintainability, and scope review.
10. Commit.
11. Push.
12. Create or update the PR.
13. Stop at the requested phase boundary.

**MUST NOT:** Start the next Jira phase, feature, cleanup, or refactor unless explicitly requested.

**MUST NOT:** Merge a PR unless the user explicitly asks to merge it.

If a foundational defect is inside the current task scope, fix it now rather than deliberately leaving known bad foundations for later.

If an unrelated issue is discovered, report it instead of silently expanding scope.

## 24. Git and Pull Request Workflow

For normal implementation work:

- Start from the latest intended base branch.
- Keep one task/phase on one focused branch unless instructed otherwise.
- Do not discard or overwrite unrelated local/user work.
- Do not force-push or rewrite shared history unless explicitly required.
- Do not mix unrelated cleanup into a feature PR.
- Inspect `git status`, the complete diff, and `git diff --check` before completion.
- Push the final validated branch.
- Create or update the requested PR.
- Do not merge without explicit user instruction.

PR descriptions must not be empty.

A meaningful PR body should include, as applicable:

- task/phase scope;
- architecture/design decisions;
- security and data-integrity decisions;
- important trade-offs;
- migrations/schema changes;
- tests and validation executed;
- intentionally deferred work;
- known follow-up items.

If a PR already exists for the branch, update that PR instead of opening a duplicate.

## 25. Makefile-First Validation

The root `Makefile` is the standard interface for routine Nexus local validation.

**MUST:** Inspect the current `Makefile` before final validation because targets may evolve.

Prefer existing Make targets over reconstructing long Docker, pytest, npm, lint, type-check, or build commands manually.

Current standard targets include:

```bash
make backend-check
make frontend-check
make docker-check
make check
```

Use them according to the affected scope:

- Backend-only changes: run focused tests while developing, then `make backend-check`.
- Frontend-only changes: run focused tests while developing, then `make frontend-check`.
- Docker/infrastructure changes: run the relevant focused validation and `make docker-check`.
- Before declaring a PR fully ready, prefer `make check` to mirror the complete local Nexus CI workflow unless the task explicitly limits validation or the current Makefile defines a better target.

Focused raw commands are allowed for debugging a specific failure or quickly exercising the exact changed tests.

**MUST NOT:** Replace an existing Make target with a complicated ad-hoc command merely because the agent can construct one.

If a Make target fails:

1. inspect the actual failure;
2. run a focused underlying command only when useful for diagnosis;
3. fix the cause;
4. rerun the Make target.

Do not bypass or weaken checks.

If not already included by the current Makefile, also run the repository's required quality checks such as:

```bash
pre-commit run --all-files
git diff --check
```

Do not weaken Ruff, mypy, pytest, coverage, frontend lint/type-check, pre-commit, or CI configuration just to make a task pass.

## 26. Testing Standard

Tests must protect behavior and boundaries, not merely increase coverage.

### MUST

- Add regression tests for bugs.
- Add meaningful tests for new behavior.
- Use real PostgreSQL integration tests when behavior depends on PostgreSQL constraints, transactions, indexes, migrations, or SQLAlchemy persistence semantics.
- Test security-sensitive tenant/resource boundaries explicitly.
- Test failure behavior, not only happy paths.
- Preserve deterministic test behavior.
- Keep returned domain/application objects independent from live ORM session state where that is an architectural requirement.
- Mirror current CI through the Makefile before declaring work complete.

### MUST NOT

- Mock away the behavior being tested in an integration test.
- Delete a failing test merely to pass CI.
- Weaken an assertion without a technical reason.
- Skip security/integrity tests for convenience.
- claim a check passed unless it was actually executed successfully.

When a test requires an external service or database that Nexus deliberately provides through Docker/Make targets, use the repository-provided workflow rather than inventing a parallel setup.

## 27. Backend Architecture Defaults

For backend features, preserve clear responsibility boundaries.

A typical API flow may be:

```text
FastAPI Router / Controller
        ↓
Application Use Case / Service
        ↓
Port / Repository Contract
        ↓
Infrastructure Adapter
        ↓
PostgreSQL / External Provider
```

This is a guide, not a requirement to create a layer for every feature.

### Boundaries

- Controllers handle transport concerns and translate HTTP input/output.
- Application/use-case code owns business orchestration and transaction decisions.
- Repositories/adapters own persistence or external-system mechanics.
- Domain contracts must not depend on FastAPI, SQLAlchemy, provider SDKs, or transport schemas.
- Infrastructure may depend on domain/ports to implement them.
- Internal database IDs must not leak into public/domain boundaries unless explicitly designed.
- Authorization and authentication remain separate responsibilities.
- Tenant filtering is defense in depth and does not replace authorization.

Do not hold a database transaction open across slow external network calls or LLM streaming unless an explicitly reviewed design requires it.

Do not call blocking synchronous persistence directly from an async event loop without an explicit execution-boundary design.

## 28. Final Agent Report

At the end of an implementation task, report concisely:

- what changed;
- files or major areas changed;
- important architecture/security decisions;
- tests added/updated;
- focused validation results if relevant;
- Makefile validation results;
- pre-commit and `git diff --check` results when required;
- commit SHA;
- pushed branch;
- PR URL;
- current CI status when available;
- anything requiring human review before merge;
- intentionally deferred work.

Do not paste huge successful command logs. Summarize pass/fail counts and include detailed logs only when they explain a failure.


## 29. Golden Rule

> **Understand first. Scope locally. Follow the documented architecture. Make the smallest safe change. Test it. Expand only when evidence requires it.**
