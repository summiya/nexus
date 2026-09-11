# NEXUS Task Specification Template

Use this template before moving a task to `READY`.

The specification is normally prepared by the human and/or ChatGPT.
It is not a separate mandatory Codex agent step.

```yaml
---
spec_version: 1
status: ready_for_build
github_issue: ""
task_type: feature
primary_domain: ""
related_domains: []
risk_level: low
human_approval: not_required
max_remediation_rounds: 3
capability: ""
release_boundary: ""
security_impact: none
api_impact: none
data_model_impact: none
architecture_impact: none
observability_impact: none
documentation_impact: none
---
```

## 1. Summary

Describe the task in a few sentences.

## 2. Problem

What problem exists today?

## 3. Current Behavior

Describe what currently happens.

## 4. Desired Behavior

Describe exactly what should happen after implementation.

## 5. Scope

List what the Builder is allowed to change.

## 6. Non-Goals

List what must not be changed as part of this task.

## 7. Acceptance Criteria

Use testable criteria:

- AC-001:
- AC-002:
- AC-003:

## 8. Tests Required

Describe the tests needed to prove the acceptance criteria.

## 9. Domain

Primary domain:

Related domains, if any:

## 10. Architecture and Invariants

Describe relevant architecture constraints and invariants.

## 11. Security

Describe authentication, authorization, isolation, secrets, validation, or other security requirements.

## 12. API / Data Model

Describe any API or persistence impact.

## 13. Observability

Describe required logs, metrics, tracing, audit records, or execution events.

## 14. Documentation

List documentation that must be updated.

## 15. Human Approval

Choose:

- `not_required`
- `required_before_build`
- `required_before_merge`

Explain why if approval is required.

## 16. Builder Instructions

Specific implementation constraints.

## 17. Tester Instructions

Specific behaviors and edge cases to verify.

## 18. Reviewer Instructions

Specific architecture, security, scope, or contract concerns to inspect.

## 19. Clarifications

Record decisions made by the human before implementation.

## 20. Definition of Ready

A task is ready only when:
- the problem is clear;
- desired behavior is clear;
- acceptance criteria are testable;
- scope and non-goals are clear;
- relevant domain is known;
- required approvals are known;
- required tests are identified;
- no unresolved invariant conflict exists.
