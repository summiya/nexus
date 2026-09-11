# NEXUS Engineering Workflow

## Goal

Provide a simple, controlled engineering loop for NEXUS while minimizing unnecessary Codex usage.

The specification is prepared by the human and/or ChatGPT.
A separate Specification Agent is **not** part of the default automated loop.

## Main Flow

```text
┌──────────────┐
│ HUMAN        │
│ Define task  │
└──────┬───────┘
       ↓
┌──────────────┐
│ SPECIFICATION│
│ Human/ChatGPT│
└──────┬───────┘
       ↓
┌──────────────┐
│ READY        │
└──────┬───────┘
       ↓
┌──────────────┐
│ BUILDER      │
└──────┬───────┘
       ↓
┌──────────────┐
│ TESTER       │
└──────┬───────┘
       ↓
┌──────────────┐
│ REVIEWER     │
└──────┬───────┘
       ↓
┌──────────────┐
│ HUMAN REVIEW │
└──────┬───────┘
       ↓
     MERGE
```

## Failure Loops

### Tester Finding

```text
TESTER
  ↓
FIXER
  ↓
TESTER
```

### Reviewer Finding

```text
REVIEWER
  ↓
FIXER
  ↓
TESTER
  ↓
REVIEWER
```

The Tester always verifies a Fixer change before the Reviewer gets final control.

## Maximum Remediation

There are at most **3 automated remediation rounds per task**.

```text
Round 1 → Fix → Verify
Round 2 → Fix → Verify
Round 3 → Fix → Verify
```

If the issue remains after round 3:

```text
AUTOMATION STOPPED
        ↓
HUMAN INTERVENTION
        ↓
PR REMAINS OPEN
```

There is never an automatic round 4.

## Recommended GitHub Project States

| State | Owner | Meaning |
|---|---|---|
| BACKLOG | Human | Task exists but is not ready |
| READY | Human | Specification is complete and task can be built |
| BUILDING | Builder | Implementation in progress |
| TESTING | Tester | Independent verification |
| REVIEWING | Reviewer | Engineering review |
| FIXING | Fixer | Confirmed finding is being remediated |
| HUMAN REVIEW | Human | Final approval required |
| BLOCKED | Human/Agent | Cannot safely continue |
| AUTOMATION STOPPED | System/Human | Three remediation rounds exhausted or hard stop |
| DONE | Human | PR merged/accepted |

## Gates

### READY → BUILDING

Requires:
- specification exists;
- acceptance criteria are clear;
- required approvals exist;
- no known invariant conflict.

### BUILDING → TESTING

Requires:
- Builder implementation complete;
- relevant tests executed;
- Builder handoff produced.

### TESTING → REVIEWING

Requires:
- Tester passes;
- no unresolved blocking findings.

### REVIEWING → HUMAN REVIEW

Requires:
- Reviewer passes;
- no unresolved blocking findings.

### HUMAN REVIEW → MERGE

Requires:
- human approval.

Agents must not merge automatically.

## Hard Stops

Stop automation immediately for:
- invariant violation;
- security weakening;
- authentication/authorization bypass;
- tenant/project isolation violation;
- secret exposure;
- unapproved major architecture change;
- unapproved public API change;
- unapproved data-model/migration change;
- unapproved core agent-execution semantic change;
- unsafe infrastructure/dependency change.

A hard stop requires human intervention.

## Authority

Use this order when sources conflict:

```text
Platform/System Safety
→ INVARIANTS.md
→ AGENTS.md
→ Approved Architecture/Security/Global Docs
→ Task Specification
→ GitHub Task Details
→ Assumptions
```

Do not resolve a higher-level conflict by inventing a lower-level interpretation.

## Scope

Every task should have:
- a clear problem;
- desired behavior;
- acceptance criteria;
- explicit non-goals;
- relevant domain;
- relevant tests;
- known impact.

Unrelated issues may be reported but should not be silently fixed.

## Evidence

Every agent must report truthful evidence:
- files changed;
- commands run;
- test results;
- relevant findings;
- blockers;
- approval requirements.

Never claim validation that did not occur.

## GitHub Automation Boundary

GitHub Projects/Issues can represent state and trigger orchestration.

The workflow documents define what each agent is allowed to do.

Separate automation may later connect:
- Project state changes;
- Codex execution;
- PR creation;
- CI/test results;
- review events;
- remediation counters;
- human escalation.

These documents alone do not create those integrations.
