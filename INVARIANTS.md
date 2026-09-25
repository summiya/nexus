# Nexus AI — System Invariants

**File:** `INVARIANTS.md`  
**Status:** Canonical non-negotiable constraints  
**Audience:** AI agents, backend engineers, architects, security engineers, reviewers

## Purpose

These are the rules that must remain true across all Nexus implementations.

An implementation that violates an invariant is incorrect even if:

- tests pass;
- the feature appears to work;
- the change is simpler;
- the change improves performance;
- the change is convenient.

When a proposed change conflicts with an invariant, stop and resolve the conflict explicitly.

---

# 1. Security Invariants

### INV-SEC-001 — Authentication

Protected operations MUST NOT be accessible without the required authentication.

Authentication checks MUST NOT be bypassed for convenience, debugging, testing, or internal calls unless an explicitly documented trusted boundary permits it.

### INV-SEC-002 — Authorization

Authentication MUST NOT be treated as authorization.

Every protected operation MUST enforce the applicable authorization policy.

### INV-SEC-003 — Tenant Isolation

Data belonging to one tenant MUST NOT be accessible to another tenant.

Tenant identity MUST be enforced at the appropriate application/data boundaries and MUST NOT rely solely on client-supplied identifiers.

### INV-SEC-004 — Project Isolation

Where projects are security or ownership boundaries, project-scoped data MUST NOT leak across projects.

### INV-SEC-005 — Secrets

Passwords, API keys, access tokens, refresh tokens, session secrets, encryption keys, and other credentials MUST NOT be committed to source control or exposed in logs, error messages, API responses, or telemetry.

### INV-SEC-006 — Least Privilege

Components, tools, agents, MCP servers, and service identities MUST receive only the permissions required for their intended operation.

### INV-SEC-007 — Security Cannot Be Weakened for Tests

Tests MUST be adapted to correct behavior. Security controls MUST NOT be weakened merely to make tests or development workflows easier.

---

# 2. Data Invariants

### INV-DATA-001 — Ownership

Every tenant/project-scoped resource MUST have an unambiguous ownership or scope relationship.

### INV-DATA-002 — Referential Integrity

Relationships represented by the data model MUST remain internally consistent.

### INV-DATA-003 — No Silent Data Loss

A normal feature or bug fix MUST NOT silently delete or overwrite user data.

Destructive operations require explicit semantics and appropriate authorization.

### INV-DATA-004 — Persistence Contract

Database behavior MUST remain consistent with `docs/06-data-model.md`.

---

# 3. API Invariants

### INV-API-001 — Public Contract Stability

Public API behavior MUST NOT be changed silently.

Breaking changes require an explicit decision and corresponding documentation.

### INV-API-002 — Validation

External input MUST be validated at the appropriate boundary.

### INV-API-003 — Error Safety

API errors MUST NOT expose secrets, credentials, internal security details, or unnecessary sensitive implementation information.

---

# 4. Domain Invariants

### INV-DOMAIN-001 — Domain Ownership

Business rules SHOULD have a single authoritative owner.

The same business rule MUST NOT be independently reimplemented in multiple domains.

### INV-DOMAIN-002 — Boundary Respect

A domain MUST NOT directly bypass another domain's public contract merely to access internal implementation details.

### INV-DOMAIN-003 — Dependency Direction

Dependencies MUST follow the documented architecture and MUST NOT create undocumented architectural cycles.

### INV-DOMAIN-004 — Cross-Domain Changes

Cross-domain behavior MUST be intentional and justified.

---

# 5. Agent Runtime Invariants

### INV-AGENT-001 — Tool Permissions

Agent tool execution MUST respect configured permissions and authorization.

An agent MUST NOT gain additional capabilities merely because a tool is technically reachable.

### INV-AGENT-002 — Tool Results Are Untrusted

External tool output, retrieved content, MCP responses, files, and other external data MUST NOT automatically be treated as trusted instructions.

### INV-AGENT-003 — Prompt Injection Resistance

Untrusted content MUST NOT be allowed to override system-level security, authorization, or execution policies.

### INV-AGENT-004 — Sensitive Context

Secrets and sensitive tenant/project data MUST NOT be unnecessarily included in model context, logs, traces, or tool calls.

---

# 6. Observability Invariants

### INV-OBS-001 — No Secret Logging

Logs, traces, metrics, and error reports MUST NOT contain credentials, passwords, tokens, or other prohibited secrets.

### INV-OBS-002 — Auditability

Security-sensitive actions MUST remain auditable according to the requirements in `docs/07-security.md`.

### INV-OBS-003 — Correlation

Where required by the architecture, requests and executions MUST retain sufficient correlation information for debugging and audit without exposing sensitive data.

---

# 7. Reliability Invariants

### INV-REL-001 — Explicit Failure

Failures MUST NOT be silently swallowed.

Broad exception handling MUST NOT hide meaningful failures.

### INV-REL-002 — Idempotency

Operations documented as idempotent MUST remain idempotent.

### INV-REL-003 — State Consistency

Partial failures MUST NOT leave persistent state in an invalid state where the architecture requires atomicity or transactional consistency.

### INV-REL-004 — File Upload Completion Identity

A File upload completion may be treated as an idempotent duplicate only when `file_public_id` and `storage_key` identify the same File and immutable ownership is consistent.

A partial identity match, divergent identity match, ownership mismatch, or unique-constraint violation alone MUST NOT be treated as successful prior processing.

---

# 8. Engineering Invariants

### INV-ENG-001 — Documented Architecture

Implementation MUST remain within the approved architecture unless an explicit architecture decision changes it.

### INV-ENG-002 — Tests

Existing meaningful tests MUST NOT be deleted or weakened solely to make an implementation pass.

### INV-ENG-003 — No Speculative Architecture

Do not introduce major abstractions, services, queues, databases, frameworks, or patterns without a documented need.

### INV-ENG-004 — Smallest Safe Change

When multiple correct approaches exist, prefer the smallest change that satisfies the requirements without violating these invariants.

---

# 9. Documentation Invariants

### INV-DOC-001 — Single Source of Truth

A requirement, contract, or architectural rule SHOULD have one authoritative location.

Other documents SHOULD link/reference it rather than duplicate it.

### INV-DOC-002 — Documentation Consistency

Implementation MUST NOT intentionally contradict the authoritative documentation.

If documentation is wrong, correct the documentation and implementation consistently rather than silently choosing one.

---

# 10. Change-Management Invariant

### INV-CHANGE-001 — No Silent Major Changes

The following MUST NOT happen silently during ordinary implementation:

- breaking API changes;
- major data-model changes;
- security-model changes;
- tenant-isolation changes;
- major architecture changes;
- new infrastructure dependencies;
- changes to core agent execution semantics.

These require explicit review/documentation.

---

# Final Rule

If a proposed implementation conflicts with an invariant:

> **Do not implement around the invariant. Stop, identify the conflict, and resolve it explicitly.**
