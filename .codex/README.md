# NEXUS Codex Engineering Workflow

## Purpose

This directory defines the controlled multi-agent engineering workflow for NEXUS. Jira is the engineering state source of truth; GitHub is the code, PR, and CI system; Codex agents are specialized workers.

The planning stage is now an explicit Planner Agent stage. The Builder does not replace the Planner and does not start until the plan has passed the human approval gate.

## Workflow

```text
Jira READY
  ↓
Jira PLANNING
  ↓
Planner (read-only)
  ↓
Implementation Plan
  ↓
Jira AWAITING APPROVAL
  ↓
Human approval
  ↓
Jira BUILDING
  ↓
Builder (write)
  ↓
GitHub PR
  ↓
Tester (read-only)
  ↓
Reviewer (read-only)
  ↓
Fixer (write) when required
  ↓
Human Review
  ↓
Merge
```

If Tester or Reviewer finds an actionable problem:

```text
Tester/Reviewer → Fixer → Tester → Reviewer
```

Maximum automated remediation rounds: **3**. After 3 unsuccessful rounds, automation stops and human intervention is required.

## Agents

| Agent | Responsibility | Can modify implementation? |
|---|---|---:|
| Planner | Inspect Jira requirement and repository; produce structured implementation plan | No |
| Builder | Implement the human-approved plan | Yes |
| Tester | Independently verify the implementation | No |
| Reviewer | Independently review engineering quality | No |
| Fixer | Correct confirmed findings | Yes |

## Human Responsibilities

The human:
- defines or approves the task specification;
- approves the Planner handoff before implementation;
- performs final PR review;
- merges the PR.

No agent may merge a PR automatically.

## Core Rules

1. `INVARIANTS.md` is non-negotiable.
2. Follow `AGENTS.md` and the documented architecture.
3. The Planner is read-only and must not modify the repository.
4. The Builder may implement only after the human approval gate.
5. Make the smallest safe change.
6. Do not delete or weaken meaningful tests.
7. Do not bypass authentication, authorization, isolation, or security controls.
8. Do not silently introduce major architecture, API, data-model, security, infrastructure, or agent-execution changes.
9. Do not add unapproved dependencies or services.
10. Keep unrelated fixes out of the task.
11. Report uncertainty instead of inventing requirements.
12. Human approval is always required before merge.

## Artifacts

- `.codex/planner-agent.md` — Planner operating contract.
- `.codex/planner-prompt.md` — Planner execution prompt template.
- `.codex/schemas/implementation-plan.json` — Structured Planner → Builder handoff schema.
- `.codex/builder-agent.md` — Builder operating contract.
- `.codex/tester-agent.md` — Tester operating contract.
- `.codex/reviewer-agent.md` — Reviewer operating contract.
- `.codex/fixer-agent.md` — Fixer operating contract.
- `.codex/workflow.md` — End-to-end state machine and gates.

These files define agent behavior. GitHub Actions and Jira Automation provide the actual triggers and orchestration.
