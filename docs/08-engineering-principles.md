# Nexus AI — Engineering Principles

**File:** `docs/08-engineering-principles.md`  
**Status:** Canonical engineering principles  
**Audience:** AI coding agents, backend engineers, architects, reviewers

## 1. Purpose

These principles define how Nexus code should be designed and implemented.

Requirements, architecture, API contracts, data models, and security requirements remain authoritative. These principles guide implementation decisions within those constraints.

---

## 2. Rule Levels

- **MUST** — mandatory.
- **MUST NOT** — prohibited.
- **SHOULD** — strong default unless there is a documented reason not to.
- **MAY** — optional when useful.

When principles conflict with `INVARIANTS.md`, invariants win.

---

## 3. Simplicity

- MUST prefer the simplest design that satisfies the requirements.
- MUST NOT introduce abstractions without a real need.
- MUST NOT build speculative infrastructure.
- SHOULD reuse existing mechanisms when they are appropriate.
- SHOULD optimize for readability and maintainability before cleverness.

---

## 4. Separation of Concerns

- Each component SHOULD have a clear responsibility.
- Business logic SHOULD remain separate from transport, persistence, and infrastructure concerns.
- API routes SHOULD remain thin.
- Domain rules SHOULD live in the owning domain.
- Infrastructure details SHOULD NOT leak unnecessarily into domain logic.

---

## 5. SOLID

Nexus code SHOULD follow SOLID principles:

- **Single Responsibility:** one component should have one coherent responsibility.
- **Open/Closed:** extend behavior without unnecessary modification of stable code.
- **Liskov Substitution:** implementations must honor the contracts of their abstractions.
- **Interface Segregation:** prefer focused interfaces over large interfaces.
- **Dependency Inversion:** higher-level business logic SHOULD depend on stable abstractions rather than concrete infrastructure.

SOLID MUST NOT be used as an excuse to create unnecessary layers or abstractions.

---

## 6. Domain Boundaries

- Every major domain SHOULD have clear ownership.
- Business rules MUST have an authoritative owner.
- Domains MUST NOT bypass another domain's public contract to access internal implementation details.
- Cross-domain dependencies MUST be intentional.
- Duplicate business logic across domains MUST be avoided.

---

## 7. Dependency Direction

- Dependencies MUST follow the documented architecture.
- Infrastructure SHOULD depend on application/domain contracts rather than forcing domain logic to depend on infrastructure details.
- Circular dependencies MUST NOT be introduced.
- New dependencies SHOULD be justified by a real requirement.

---

## 8. API Contracts

- Public APIs MUST follow `docs/03-api-contract.md`.
- API input MUST be validated at the boundary.
- API responses and errors SHOULD be predictable and consistent.
- Breaking changes MUST NOT be introduced silently.
- API implementation MUST NOT become the source of undocumented business rules.

---

## 9. Data and Persistence

- Persistence MUST follow `docs/06-data-model.md`.
- Database access SHOULD be isolated behind appropriate repository/data-access boundaries.
- Transactions SHOULD be used where atomicity is required.
- Schema changes MUST use the project's migration mechanism.
- Data integrity and tenant/project isolation MUST be preserved.

---

## 10. Security by Default

- Security MUST be considered part of implementation, not an afterthought.
- Secure defaults MUST be preferred.
- Least privilege SHOULD be the default.
- Secrets MUST NOT appear in source, logs, test fixtures, or API responses.
- Authentication and authorization MUST NOT be bypassed.
- Detailed security requirements are defined in `docs/07-security.md`.
- `INVARIANTS.md` contains non-negotiable security constraints.

---

## 11. Error Handling

- Errors MUST NOT be silently swallowed.
- Exceptions SHOULD be handled at the layer that can make an appropriate decision.
- Broad exception handling SHOULD be avoided.
- User-facing errors SHOULD NOT expose internal implementation details or secrets.
- Error behavior SHOULD remain consistent across equivalent APIs.

---

## 12. Testing

- Every meaningful behavior change SHOULD have automated tests.
- Bugs SHOULD receive regression tests.
- Domain logic SHOULD have focused unit tests.
- Boundary behavior SHOULD have integration/API tests where appropriate.
- Tests MUST NOT be weakened or deleted simply to make an implementation pass.
- Tests SHOULD verify behavior and contracts rather than implementation details where practical.

---

## 13. Observability

- Important operations SHOULD be observable through appropriate logs, metrics, or traces.
- Logs MUST NOT contain secrets or prohibited sensitive information.
- Correlation identifiers SHOULD be preserved where required for debugging.
- Observability MUST NOT change business behavior merely to make debugging easier.

---

## 14. Twelve-Factor Principles

Where applicable, Nexus SHOULD follow Twelve-Factor practices:

- configuration through environment/configuration management;
- stateless application processes where practical;
- explicit dependencies;
- reproducible builds;
- logs treated as event streams;
- separate build, release, and run concerns;
- graceful process lifecycle;
- environment parity between development and production.

These principles are applied pragmatically and MUST NOT override Nexus-specific architecture or requirements.

---

## 15. Code Quality

- Code MUST be understandable to another engineer.
- Names SHOULD describe intent.
- Functions and classes SHOULD remain focused.
- Dead code SHOULD be removed when safely identified.
- Formatting and linting SHOULD follow project tooling.
- Unrelated formatting churn MUST be avoided in focused changes.

---

## 16. AI Agent Implementation Rules

AI agents:

- MUST follow `AGENTS.md`.
- MUST preserve `INVARIANTS.md`.
- MUST use `docs/domain-map.md` for routing.
- MUST load only the documentation relevant to the task.
- MUST inspect existing source and tests before making substantial changes.
- MUST NOT invent major architecture silently.
- MUST NOT perform unrelated cleanup.
- MUST make the smallest safe change.
- MUST test the change.

---

## 17. Cross-Domain Changes

When a task crosses domain boundaries:

1. Identify the dependency.
2. Read only the relevant documentation for the additional domain.
3. Preserve both domains' contracts.
4. Add appropriate tests.
5. Document important architectural consequences.

Cross-domain work is acceptable when technically necessary. Unnecessary cross-domain coupling is not.

---

## 18. Architecture Changes

Local implementation choices MAY be made by the agent when they remain within the approved architecture.

Major architectural changes MUST NOT be introduced silently.

Examples include:

- introducing a new infrastructure system;
- changing core execution architecture;
- changing domain ownership;
- changing public API strategy;
- changing persistence architecture;
- changing core security boundaries.

Use `docs/decisions/` for significant architectural decisions.

---

## 19. Documentation

- Documentation MUST have a clear authoritative owner.
- MUST NOT duplicate the same rule across many documents unnecessarily.
- If implementation changes an API, architecture, security requirement, data contract, or important behavior, the relevant authoritative documentation SHOULD be updated.
- Domain documentation SHOULD describe domain-specific behavior rather than repeat global rules.

---

## 20. Final Decision Rule

When multiple implementations satisfy the requirements, prefer the one that is:

1. correct;
2. secure;
3. consistent with the architecture;
4. simple;
5. testable;
6. maintainable;
7. smallest in scope.

> **Build the simplest secure, maintainable solution that satisfies the documented Nexus requirements while preserving architecture, contracts, invariants, and domain boundaries.**
