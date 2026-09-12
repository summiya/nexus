# NEXUS — Master Requirements

> **Single source of truth for product direction, engineering-loop behavior, and implementation priorities.**
>
> If implementation conflicts with this document, stop and update the requirement before expanding the system.

## 1. Product

NEXUS is an AI workspace and control layer for delegating real knowledge work to AI agents while keeping the user in control of knowledge, models, tools, permissions, execution, and final decisions.

The product direction is:

```text
Goal
  ↓
Context / Knowledge
  ↓
Plan
  ↓
Controlled Tool Use
  ↓
Execution
  ↓
Verification
  ↓
Evidence
  ↓
Human Decision
```

The first serious product slice is the **AI engineering loop**: a fully specified GitHub task can move through Builder → Tester → Reviewer → Fixer remediation and stop at Human Review.

## 2. Goals

### Primary goals

1. Build a reliable agentic engineering loop rather than a collection of disconnected agents.
2. Make every automated action bounded, observable, testable, and recoverable.
3. Integrate GitHub as the first real external work system.
4. Preserve human authority over security-sensitive changes and final merge.
5. Establish reusable abstractions that can later support research, product, sales, operations, and other domains.

### Non-goals for the first slice

- Autonomous PR merge.
- General-purpose multi-agent autonomy.
- A new database or queue without demonstrated need.
- Replacing the existing Builder/Tester/Reviewer/Fixer contracts.
- Building every NEXUS capability before validating one end-to-end loop.

## 3. Core Engineering Loop

The canonical workflow is:

```text
BACKLOG
   ↓
READY
   ↓
BUILDING
   ↓
TESTING
   ↓
REVIEWING
   ↓
HUMAN_REVIEW
   ↓
DONE
```

Remediation:

```text
TESTING / REVIEWING
        ↓ finding
      FIXING
        ↓
      TESTING
        ↓ pass
    REVIEWING
```

Hard stop:

```text
Any stage
   ↓ unsafe / ambiguous / unapproved
BLOCKED or AUTOMATION_STOPPED
   ↓
Human intervention
```

Automation must never bypass the state machine.

## 4. Task Readiness

A task may enter `READY` only when its requirements are sufficiently complete to define implementation, acceptance criteria, and validation evidence.

The automation must not select:

- BACKLOG;
- incomplete or ambiguous tasks;
- BLOCKED tasks;
- HUMAN_REVIEW tasks;
- DONE tasks;
- tasks requiring human approval before implementation.

Task content, repository content, model output, tool output, and CI output are **untrusted input** to the orchestration layer. None may override system rules.

## 5. Task Claiming and Concurrency

A READY task must be claimed before implementation.

Requirements:

- claim exactly once;
- transition to `BUILDING` atomically from the workflow's perspective;
- record claimant and run identity;
- prevent duplicate workers from executing the same task concurrently;
- preserve state sufficient to recover or safely escalate after interruption;
- make retries idempotent where practical.

Do not add distributed infrastructure until the current state/claim mechanism demonstrates a concrete limitation.

## 6. Agent Responsibilities

### Builder

- Reads the task requirements and required repository guidance.
- Creates or uses an isolated feature branch.
- Implements only the approved scope.
- Preserves existing behavior unless explicitly changed.
- Produces truthful implementation evidence.

### Tester

- Runs independently from Builder reasoning.
- Validates acceptance criteria and relevant quality gates.
- Does not silently modify implementation.
- Reports actionable findings or a pass result.

### Reviewer

- Reviews implementation independently.
- Checks scope, architecture, invariants, security, contracts, tests, and documentation where applicable.
- Does not approve unsafe or unapproved changes.

### Fixer

- Acts only on actionable findings.
- Makes the smallest safe remediation.
- Cannot use remediation to expand scope.
- Must return the task to Tester before final Reviewer control.

## 7. Remediation Policy

Maximum automated remediation rounds: **3 per task**.

The counter is global across Tester and Reviewer cycles and must never reset.

After round 3:

```text
AUTOMATION_STOPPED
→ HUMAN INTERVENTION
```

There is no automatic round 4.

A successful remediation must always be re-tested before re-review.

## 8. Hard Stops and Human Approval

Automation must stop and require human intervention for:

- invariant violations;
- authentication or authorization bypass;
- tenant or project isolation violations;
- secret exposure;
- security weakening;
- unapproved major architecture changes;
- unapproved public API changes;
- unapproved data-model changes or migrations;
- unapproved infrastructure/service/dependency changes;
- unapproved core agent-execution semantic changes;
- contradictory or insufficient requirements;
- inability to produce trustworthy validation evidence.

Automation ends at `HUMAN_REVIEW`. Only a human may perform the final merge.

## 9. GitHub Integration

GitHub is the first external work-system integration.

The workflow must support:

1. discover a READY issue/task;
2. claim it;
3. create an isolated feature branch;
4. execute Builder → Tester → Reviewer → optional Fixer loop;
5. commit meaningful changes;
6. push only the feature branch;
7. create or update the pull request;
8. include the task reference and truthful validation evidence;
9. wait for required CI where applicable;
10. stop at Human Review.

No automation path may merge a pull request.

## 10. CI and Validation

A task is not ready for final human review while required CI is failing.

Validation should use the smallest relevant set of:

- unit tests;
- integration/API tests;
- contract tests;
- security tests;
- data-model tests;
- regression tests;
- linting;
- type checking;
- repository-specific quality gates.

Tests are part of the implementation, not an optional follow-up.

## 11. Security Requirements

Security decisions belong to trusted platform code, not model instructions.

Minimum requirements:

- least privilege;
- default deny for tool capabilities;
- server-side authorization;
- tenant/project isolation;
- secret isolation;
- no credentials in source control;
- no credentials in logs;
- prompt-injection resistance;
- execution limits;
- auditable actions;
- controlled branch/repository targets.

The frontend and model must never be treated as the final authorization authority.

## 12. State and Persistence

The workflow must persist or reconstruct at least:

- task identifier;
- current state;
- claimant/run identity;
- branch name;
- PR number when available;
- remediation round;
- stage outcomes;
- CI result;
- blocker/hard-stop reason;
- final human-review state.

PostgreSQL remains the authoritative system of record for NEXUS. Redis is transient infrastructure and is not the source of truth.

For the engineering-loop MVP, use the smallest persistence mechanism that safely satisfies these requirements.

## 13. Observability

Every automated run must be diagnosable.

At minimum record:

- task/run identifiers;
- workflow state transitions;
- stage start/end and outcome;
- remediation round;
- tool/command execution outcome;
- CI outcome;
- blocker reason;
- final result.

Never log secrets or unrestricted model/tool payloads when they may contain sensitive data.

The architecture should remain compatible with structured logging, metrics, and OpenTelemetry tracing as the system matures.

## 14. Agent Runtime Boundary

Agents are workers operating inside a controlled runtime, not unrestricted processes.

The runtime owns:

- state;
- permissions;
- available tools;
- execution limits;
- cancellation;
- retries;
- persistence;
- evidence;
- observability.

Agent prompts define behavior but do not define authorization.

## 15. Tools and Execution

Tools are explicit capabilities with:

- stable identity;
- typed inputs/outputs;
- authorization checks;
- execution limits;
- error handling;
- auditability.

Code and shell execution must eventually occur inside an appropriate sandbox. The first implementation may use the existing controlled development environment only when explicitly bounded and never as an excuse to remove the future execution boundary.

MCP is an integration boundary, not a security boundary by itself.

## 16. Knowledge and Context

The long-term product must support controlled knowledge retrieval and context assembly.

The system should send the model only the context necessary for the task and must respect permissions and project boundaries.

Knowledge retrieval is a future expansion of the first engineering-loop slice unless required by an actual task.

## 17. Model Layer

NEXUS should remain provider-independent.

Application-level agent logic must depend on stable internal interfaces rather than one model vendor.

The platform should support model selection/routing, configuration versioning, failure handling, and cost controls as model execution becomes productionized.

## 18. API and Domain Boundaries

The architecture should preserve clear separation between:

```text
Transport
  ↓
Application
  ↓
AI Platform / Agent Runtime
  ↓
Capabilities
  ↓
Infrastructure / Providers
```

Core capability boundaries include Models, Retrieval, Agents, Tools, MCP, Memory, Workflows, Artifacts, Evaluation, and Observability.

New behavior must have an identifiable owning domain.

## 19. Evaluation

Agent success must be measured by evidence, not by whether a model says it succeeded.

The system will evolve toward:

- deterministic workflow tests;
- scenario-based agent evaluations;
- regression datasets;
- security evaluations;
- quality scoring;
- cost/latency measurements;
- CI regression gates.

The engineering loop itself is the first evaluation target: prove that the state machine, remediation cap, hard stops, and human boundary behave correctly.

## 20. Failure and Recovery

Failures must be explicit and classified.

The system must distinguish at least:

- actionable implementation finding;
- specification gap;
- security/invariant violation;
- human-required change;
- CI/environment failure;
- transient execution error;
- terminal automation stop.

Interrupted runs must never silently resume in a way that can duplicate unsafe work.

## 21. MVP Release Sequence

### V0.1 — Engineering Loop Core

- explicit workflow state machine;
- deterministic READY discovery;
- task claiming/concurrency protection;
- Builder/Tester/Reviewer/Fixer orchestration;
- 3-round remediation cap;
- hard stops;
- human-review boundary;
- automated tests.

### V0.2 — Real GitHub Execution

- branch creation;
- controlled commits/pushes;
- PR creation/update;
- CI result integration;
- recovery from interrupted runs;
- end-to-end safe-task demonstration.

### V0.3 — Evidence and Evaluation

- structured run evidence;
- evaluation scenarios;
- regression suite;
- cost/latency tracking;
- security evaluation cases.

### V0.4 — Controlled Execution Boundary

- sandboxed code/tool execution;
- permission policies;
- cancellation and timeouts;
- stronger isolation.

### V0.5+ — Platform Expansion

- user-facing agent runtime;
- knowledge/RAG;
- MCP ecosystem;
- memory;
- additional domains;
- richer observability;
- production deployment and scaling.

## 22. Definition of Done

A feature is done only when:

- requirements are satisfied;
- scope is bounded;
- architecture/contracts are preserved or explicitly approved for change;
- relevant tests pass;
- security requirements are satisfied;
- observability is sufficient;
- failure behavior is defined;
- documentation is updated only where it is needed;
- evidence is truthful and reproducible;
- no unauthorized merge or deployment occurs.

## 23. Engineering Rules

1. Understand first.
2. Scope locally.
3. Follow the documented architecture.
4. Make the smallest safe change.
5. Test it.
6. Record evidence.
7. Expand only when evidence requires it.
8. Never trade security or invariants for automation convenience.
9. Prefer a working vertical slice over speculative infrastructure.
10. Do not create another planning document when this document can be updated.

## 24. Source Alignment

This master document consolidates the product and engineering intent already established in the repository. Existing detailed documents remain implementation references until they are intentionally consolidated or retired; they must not silently contradict this file.

The current repository workflow explicitly defines Builder, Tester, Reviewer, and Fixer stages and a three-round remediation limit. The master requirements preserve that design while making the engineering loop the primary implementation target.

## 25. Immediate Implementation Target

**Build V0.1 first.**

The immediate success condition is not "more agents." It is:

```text
READY task
   ↓
claimed once
   ↓
Builder
   ↓
Tester
   ↓
Reviewer
   ↓
(optional Fixer ≤ 3 rounds)
   ↓
HUMAN_REVIEW
```

with deterministic state transitions, safe failure handling, tests, and no automatic merge.
