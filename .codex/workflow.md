# NEXUS Engineering Workflow

## Goal

Provide a controlled multi-agent engineering loop for NEXUS with explicit planning, human approval, independent verification, and bounded remediation.

Jira is the engineering state source of truth. GitHub is the code, pull-request, and CI system. Codex agents are specialized workers. GitHub Actions provides execution/orchestration.

## Main Flow

```text
JIRA READY
   ↓
JIRA PLANNING
   ↓
PLANNER (read-only)
   ↓
IMPLEMENTATION PLAN
   ↓
JIRA AWAITING APPROVAL
   ↓
HUMAN APPROVAL
   ↓
JIRA BUILDING
   ↓
BUILDER (write)
   ↓
GITHUB PR
   ↓
JIRA TESTING
   ↓
TESTER (read-only)
   ↓
JIRA REVIEW
   ↓
REVIEWER (read-only)
   ↓
JIRA HUMAN REVIEW
   ↓
HUMAN MERGE
   ↓
JIRA DONE
```

## Planning Gate

### PLANNING

The Planner:
- reads the Jira requirement;
- reads repository instructions and invariants;
- identifies the owning domain;
- inspects relevant documentation, source, and tests;
- produces `.codex/schemas/implementation-plan.json` output;
- makes no repository changes.

### AWAITING APPROVAL

The plan is presented as the implementation handoff. A human must approve the plan before the task can enter `BUILDING`.

The Builder MUST NOT treat the transition into `PLANNING` as implementation authorization.

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

The Tester always verifies a Fixer change before the Reviewer receives final control.

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

## Jira States

| State | Owner | Meaning |
|---|---|---|
| TO DO | Human | Task exists but is not ready |
| READY | Human | Requirement is ready for planning |
| PLANNING | Planner | Repository-grounded implementation plan is being produced |
| AWAITING APPROVAL | Human | Plan exists and awaits implementation approval |
| BUILDING | Builder | Approved implementation is in progress |
| TESTING | Tester | Independent verification |
| REVIEW | Reviewer | Independent engineering review |
| FIXING | Fixer | Confirmed finding is being remediated |
| HUMAN REVIEW | Human | Final approval and merge decision |
| DONE | Human | PR merged/accepted |

## Gates

### READY → PLANNING

Requires:
- Jira requirement is present;
- the task is ready for repository-grounded planning.

### PLANNING → AWAITING APPROVAL

Requires:
- Planner completed read-only investigation;
- structured implementation plan was produced;
- recommendation is `ready_for_approval`;
- no unresolved hard stop exists.

If the Planner returns `needs_clarification` or `blocked`, the task must not proceed to implementation.

### AWAITING APPROVAL → BUILDING

Requires:
- human approval of the implementation plan;
- required task/assignment controls are satisfied.

### BUILDING → TESTING

Requires:
- Builder implementation complete;
- relevant tests executed;
- Builder handoff produced;
- GitHub PR exists.

### TESTING → REVIEW

Requires:
- Tester passes;
- no unresolved blocking findings.

### REVIEW → FIXING

Requires:
- Reviewer has an actionable finding.

### FIXING → TESTING

Requires:
- Fixer reports a confirmed fix;
- remediation round is 1, 2, or 3.

### REVIEW → HUMAN REVIEW

Requires:
- Reviewer passes;
- no unresolved blocking findings.

### HUMAN REVIEW → DONE

Requires:
- human approves and merges the PR.

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
- unsafe infrastructure/dependency change;
- materially ambiguous or contradictory requirements.

A hard stop requires human intervention.

## Authority

Use this order when sources conflict:

```text
Platform/System Safety
→ INVARIANTS.md
→ AGENTS.md
→ Approved Architecture/Security/Global Docs
→ Approved Implementation Plan
→ Jira Task Details
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

## Automation Boundary

Jira Automation may trigger the Planner when an issue enters `PLANNING` and may later trigger other workers on state changes.

GitHub Actions executes Codex workers and stores structured artifacts.

Jira transitions remain the authoritative lifecycle state; GitHub PR/CI state remains the authoritative code-delivery evidence.
