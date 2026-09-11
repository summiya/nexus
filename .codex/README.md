# NEXUS Codex Engineering Workflow

## Purpose

This directory defines the simple, controlled engineering workflow for NEXUS.

Specifications are prepared by the human and/or ChatGPT before a task enters `READY`.
There is **no separate Specification Agent in the default workflow**.

## Workflow

Human/ChatGPT Specification
→ GitHub Task `READY`
→ Builder
→ Tester
→ Reviewer
→ Human Review
→ Merge

If Tester or Reviewer finds an actionable problem:

Tester/Reviewer → Fixer → Tester → Reviewer

Maximum automated remediation rounds: **3**.

After 3 unsuccessful remediation rounds, automation stops and human intervention is required.

## Agents

| Agent | Responsibility | Can modify implementation? |
|---|---|---:|
| Builder | Implement the approved specification | Yes |
| Tester | Independently verify the implementation | No |
| Reviewer | Independently review engineering quality | No |
| Fixer | Correct confirmed findings | Yes |

## Human Responsibilities

The human:
- defines or approves the task specification;
- approves changes that require human approval;
- performs final PR review;
- merges the PR.

No agent may merge a PR automatically.

## Core Rules

1. `INVARIANTS.md` is non-negotiable.
2. Follow `AGENTS.md` and the documented architecture.
3. Make the smallest safe change.
4. Do not delete or weaken meaningful tests.
5. Do not bypass authentication, authorization, isolation, or security controls.
6. Do not silently introduce major architecture, API, data-model, security, infrastructure, or agent-execution changes.
7. Do not add unapproved dependencies or services.
8. Keep unrelated fixes out of the task.
9. Report uncertainty instead of inventing requirements.
10. Human approval is always required before merge.

These files define agent behavior. They do not by themselves create GitHub triggers, permissions, CI jobs, or orchestration.
