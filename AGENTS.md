# Nexus AI — Agent Instructions

**File:** `AGENTS.md`  
**Status:** Mandatory  
**Audience:** AI coding agents working on Nexus

## 1. Purpose

This file contains the default engineering and workflow rules for every Nexus task.

Task-specific prompts should describe only the task, acceptance criteria, and any exceptional constraints. The agent must apply this file automatically.

## 2. Instruction Precedence

When instructions differ, use this order:

1. Explicit current user/task instructions.
2. Approved current Jira/phase requirements.
3. Current repository implementation and tests.
4. This `AGENTS.md`.
5. Current architecture/security/data-model documentation relevant to the task.
6. Older planning or roadmap documents.

The current repository is the primary source of truth for code structure, existing abstractions, supported commands, and implemented behavior.

Older documentation may describe intended or historical structures.

**MUST NOT:** Create folders, layers, services, abstractions, or dependencies solely because an older document describes them.

**MUST:** Reconcile documentation with the actual repository before coding.

## 3. Before Every Task

Before making changes:

1. Read this `AGENTS.md`.
2. Understand the task and acceptance criteria.
3. Inspect the affected source code.
4. Inspect relevant tests.
5. Inspect relevant architecture/security/data-model documentation when the task touches those concerns.
6. Inspect the current `Makefile` before final validation.
7. Check existing patterns before creating new abstractions.
8. Only then implement.

Do not explore unrelated areas of the repository without a reason.

Expand investigation only when required by a dependency, failing test, cross-domain contract, security concern, or explicit task scope.

## 4. Current Repository Reality

Backend code currently lives under:

```text
backend/src/nexus/
backend/tests/
```

Frontend code currently lives under:

```text
frontend/
```

Do not assume a planned domain path exists.

Examples:

- Do not invent `src/nexus/auth/` because old documentation mentions it.
- Do not invent `src/nexus/models/` when the implemented LLM capability is under the current repository structure.
- Do not create `docs/domains/.../` merely because a planning document describes a future documentation layout.

Inspect the repository first and follow the implemented structure unless the current task explicitly changes it.

## 5. Engineering Principles

Apply these principles pragmatically:

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

SOLID does **not** mean creating more classes, interfaces, services, factories, or layers.

Prefer the smallest design that keeps responsibilities and boundaries clear.

### Avoid abstraction theater

Do not introduce these unless they solve a concrete current Nexus requirement:

- GenericRepository
- BaseRepository
- BaseService
- repository registries
- service locators
- DI frameworks
- Unit of Work frameworks
- command buses
- mediator layers
- generic mapper frameworks
- specification frameworks
- factories created only for theoretical future extensibility

Reuse an existing abstraction when it genuinely fits. Do not copy an existing weak pattern merely for consistency.

## 6. Scope and Phase Discipline

The current task defines the allowed scope.

### Plan-only / review-only tasks

If the task says PLAN ONLY, DESIGN ONLY, REVIEW ONLY, or equivalent:

- inspect;
- analyze;
- return the plan/review;
- do not modify files;
- do not create a branch;
- do not commit;
- do not push;
- do not create a PR.

### Implementation tasks

When implementation is approved:

1. Verify prerequisites are already on the intended base branch.
2. Sync the latest intended base branch, normally `main`.
3. Create or use the requested task/phase branch.
4. Implement only the approved task or phase.
5. Add/update tests.
6. Run focused validation while developing.
7. Run repository-standard final validation.
8. Inspect the complete diff.
9. Perform architecture, security, maintainability, and scope review.
10. Commit.
11. Push.
12. Create or update the PR.
13. Stop at the task/phase boundary.

**MUST NOT:** Start the next phase automatically.

**MUST NOT:** Merge a PR unless the user explicitly asks to merge it.

If a foundational defect is inside the current task scope, fix it now rather than knowingly building on a bad foundation.

If an unrelated issue is discovered, report it instead of silently expanding scope.

## 7. Existing Code Comes First

Before creating a new:

- service;
- repository;
- protocol;
- helper;
- mapper;
- utility;
- configuration object;
- dependency;
- infrastructure component;

search for an existing implementation and pattern first.

Reuse when appropriate.

Do not create duplicate functionality without a technical reason.

## 8. Backend Architecture Defaults

A typical backend flow may be:

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

This is a guide, not a requirement to create every layer for every feature.

### Responsibilities

**Controller / Router**
- HTTP/transport concerns;
- request/response mapping;
- transport-level validation;
- translating application errors into API responses.

**Application / Use Case / Service**
- business orchestration;
- authorization decisions;
- lifecycle decisions;
- transaction ownership;
- coordination across repositories and external capabilities.

**Repository / Port**
- capability-specific persistence contract;
- domain/application-facing types;
- no FastAPI or ORM leakage.

**Infrastructure Adapter**
- SQLAlchemy;
- provider SDKs;
- Redis;
- mail delivery;
- external systems;
- explicit domain/persistence mapping.

**Domain**
- business/domain contracts and invariants;
- independent from FastAPI, SQLAlchemy, provider SDKs, and transport schemas.

Infrastructure may depend on domain/ports to implement them. Domain must not depend on infrastructure.

## 9. Authentication, Authorization, and Tenant Safety

Authentication answers:

> Who are you?

Authorization answers:

> Are you allowed to do this?

Keep them separate.

Tenant-scoped repository filtering is defense in depth. It does not replace application authorization.

Security-sensitive repository methods should make unsafe unscoped access difficult by design.

Public/resource identities should cross application boundaries according to the current approved architecture. Internal database IDs must remain infrastructure details unless explicitly designed otherwise.

Do not trust browser/client-supplied organization IDs, user IDs, ownership, roles, or permissions as proof of authorization.

Never log secrets, OTPs, access tokens, refresh tokens, credentials, sensitive provider payloads, or private message/file content unless explicitly approved and safely redacted.

## 10. Database and Transaction Rules

Use the existing persistence architecture unless the task explicitly changes it.

Repositories may:

- add;
- query;
- update persistence state;
- flush when required.

Repositories should not own outer use-case commits/rollbacks when the current Nexus application transaction boundary owns them.

Application/use-case code owns transaction boundaries.

Do not hold a database transaction open across slow external network I/O or LLM generation/streaming unless an explicitly reviewed design requires it.

Do not call blocking synchronous database code directly from an async event loop without an explicit execution-boundary design.

Use real PostgreSQL integration tests when behavior depends on:

- PostgreSQL constraints;
- migrations;
- indexes;
- transactions;
- foreign-key semantics;
- SQLAlchemy/PostgreSQL behavior.

## 11. LLM and External Provider Boundaries

Application/domain code must not depend directly on provider SDK objects when a Nexus port/gateway exists.

Prefer:

```text
Application
    ↓
Nexus Port / Gateway
    ↓
Infrastructure Adapter
    ↓
External Provider
```

Do not leak raw provider chunks, provider exceptions, SDK request objects, or SDK response objects across established Nexus boundaries.

Do not add LangChain/LangGraph or another orchestration framework unless the current approved task requires it.

## 12. Error Handling

Use the smallest useful error contract.

Do not:

- expose SQLAlchemy exceptions as public/application contracts;
- raise FastAPI `HTTPException` from repositories/domain code;
- create large exception hierarchies without a concrete need;
- swallow unexpected failures;
- leak sensitive implementation details to API clients.

Preserve exception chaining where useful.

Normal not-found behavior should follow the capability's current contract.

## 13. New Features

For a new feature:

1. Confirm the current task/acceptance criteria.
2. Inspect the existing owning capability.
3. Check current architecture implications.
4. Check API implications if applicable.
5. Check data-model implications if applicable.
6. Check security/authorization implications.
7. Implement the smallest complete vertical change in scope.
8. Add meaningful tests.
9. Update documentation only when behavior/contracts/architecture change.

A newly approved task may legitimately supersede older planning documents. Do not reject a task merely because an old roadmap does not contain it.

## 14. Bug Fixes

For a bug:

1. reproduce it;
2. identify the root cause;
3. inspect relevant tests;
4. make the smallest safe fix;
5. add/update regression coverage;
6. run relevant validation;
7. inspect security and contract implications.

Do not:

- fix only symptoms;
- delete tests;
- weaken assertions without reason;
- weaken security;
- perform unrelated refactoring;
- silently change public behavior.

## 15. Dependencies

Before adding a dependency:

1. confirm it is required;
2. check whether Nexus already has the capability;
3. check whether an existing dependency already provides it;
4. check architecture compatibility;
5. consider security and maintenance cost;
6. update dependency configuration appropriately.

Do not add libraries for trivial helpers or duplicate capabilities.

Major dependency/infrastructure changes require explicit architectural justification.

## 16. Testing Standard

Tests must protect behavior and boundaries, not merely increase coverage.

### MUST

- add tests for new behavior;
- add regression tests for bugs;
- test failure paths where relevant;
- test security-sensitive tenant/resource boundaries explicitly;
- preserve deterministic behavior;
- use real PostgreSQL integration tests when database behavior matters;
- preserve existing tests;
- keep returned domain/application objects independent from live ORM session state when required by architecture.

### MUST NOT

- delete failing tests merely to pass CI;
- weaken assertions without a technical reason;
- skip security/integrity tests for convenience;
- mock away the behavior an integration test is supposed to prove;
- claim a test/check passed unless it was actually executed successfully.

## 17. Makefile-First Validation

The root `Makefile` is the standard interface for routine Nexus local validation.

Always inspect the current `Makefile` before final validation because targets may evolve.

Prefer Make targets over reconstructing long Docker, pytest, npm, lint, type-check, or build commands.

Current standard targets include:

```bash
make backend-check
make frontend-check
make docker-check
make check
```

Use them according to scope:

- backend-only change → focused tests while developing, then `make backend-check`;
- frontend-only change → focused tests while developing, then `make frontend-check`;
- Docker/infrastructure change → relevant focused checks plus `make docker-check`;
- before declaring a PR fully ready → prefer `make check` unless the task explicitly limits validation or the current Makefile defines a better target.

Focused raw commands are allowed for debugging a specific failure.

Do not replace an existing Make target with a complicated ad-hoc command merely because one can be constructed.

If a Make target fails:

1. inspect the actual failure;
2. run a focused underlying command only when useful;
3. fix the cause;
4. rerun the Make target.

Do not bypass or weaken checks.

If not already covered by the current Makefile, run required repository checks such as:

```bash
pre-commit run --all-files
git diff --check
```

Do not weaken Ruff, mypy, pytest, coverage, frontend lint/type-check, pre-commit, or CI configuration merely to pass a task.

## 18. Git and Pull Request Workflow

For implementation work:

- start from the latest intended base;
- use one focused task/phase branch unless instructed otherwise;
- do not discard or overwrite unrelated user work;
- do not force-push/rewrite shared history unless explicitly required;
- do not mix unrelated cleanup into the task PR;
- inspect `git status`, full diff, and `git diff --check`;
- push the final validated branch;
- create or update the requested PR;
- do not merge without explicit user instruction.

If a PR already exists for the branch, update it instead of creating a duplicate.

PR bodies must not be empty.

A useful PR body should include, where applicable:

- task/phase scope;
- architecture/design decisions;
- security/data-integrity decisions;
- migrations/schema changes;
- important trade-offs;
- tests/validation executed;
- intentionally deferred work;
- known follow-up items.

## 19. Frontend Engineering

Nexus frontend uses React + TypeScript.

When changing frontend code:

- inspect existing components, routes, hooks, API clients, state patterns, styling, and tests first;
- reuse existing components/patterns;
- use strict TypeScript;
- avoid `any` unless unavoidable and documented;
- keep server state and local UI state conceptually separate;
- keep authentication/session handling centralized;
- treat frontend authorization as UX only;
- keep backend authorization authoritative;
- handle loading/error/empty/unauthorized states intentionally;
- use semantic HTML and accessible interactions;
- do not add a frontend library unless required;
- do not scatter ad-hoc HTTP calls when an existing API layer exists;
- do not create giant components combining layout, networking, business logic, validation, and state when clearer boundaries are warranted;
- do not split code into many files merely to appear clean.

For meaningful frontend behavior changes, add/update automated tests and run the current frontend Makefile validation.

## 20. Documentation

Update documentation when a change affects:

- public API contracts;
- architecture;
- data model;
- security requirements;
- domain/capability boundaries;
- important operational behavior;
- significant dependencies.

Documentation does not need to change for every internal implementation detail.

Do not create speculative documentation trees that the repository does not currently use.

## 21. Final Engineering Review

Before declaring implementation complete, verify:

- requirements are satisfied;
- scope is correct;
- architecture is preserved;
- SOLID/KISS/YAGNI were applied pragmatically;
- no unnecessary abstraction was introduced;
- security and authorization implications were reviewed;
- tenant/resource isolation is preserved;
- data integrity is preserved;
- domain/infrastructure boundaries are preserved;
- no internal implementation detail leaks across public boundaries;
- tests protect the important behavior;
- repository-standard validation passes;
- no unrelated changes remain;
- documentation is updated only where required.

## 22. Final Agent Report

At the end of an implementation task, report concisely:

- what changed;
- major files/areas changed;
- important architecture/security decisions;
- tests added/updated;
- focused validation results where relevant;
- Makefile validation results;
- pre-commit result when required;
- `git diff --check` result;
- commit SHA;
- pushed branch;
- PR URL;
- current CI status when available;
- anything requiring human review before merge;
- intentionally deferred work.

Do not paste huge successful command logs. Summarize pass/fail results and include detailed logs only when explaining a failure.

## 23. Golden Rule

> **Understand first. Inspect the current repository. Scope locally. Preserve approved architecture. Make the smallest safe change. Test through the repository-standard workflow. Stop at the requested boundary.**
