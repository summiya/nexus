# NEXUS Production Quality Roadmap

## Purpose

This document records production-quality validation capabilities that NEXUS should introduce as the product matures. These are roadmap capabilities, not immediate infrastructure requirements. They should be implemented only when the corresponding product maturity, production-readiness requirement, or scale justifies them.

This keeps NEXUS aligned with the engineering principle of avoiding speculative infrastructure while ensuring important production-readiness work is not forgotten.

## Roadmap

| Capability | Target Stage | Priority | Purpose |
|---|---|---:|---|
| Product E2E coverage | V1 → V1.5 | High | Grow browser-level coverage around real critical user workflows as features mature |
| Controlled real-LLM integration/evaluation testing | V1.5 | High | Validate provider contracts and model behavior without making real provider calls part of every PR |
| Load testing | V1.5 | High | Validate throughput and concurrency before serious production deployment |
| Performance testing | V1.5 | High | Measure latency-sensitive paths such as streaming, RAG, agents, and workflows |
| Security testing / penetration testing | V1.5 | Critical | Validate production security posture before broader deployment |
| Advanced static-quality platform (for example SonarQube) | V2 / Optional | Medium | Add centralized quality analysis only if it provides value beyond existing CI gates |
| Mutation testing | V2 / Optional | Low | Measure test-suite effectiveness where the cost is justified |
| Distributed test execution | V2 / Scale-driven | Low | Parallelize large suites only when repository/test scale requires it |

## Browser Testing Standard

Playwright remains the NEXUS browser and E2E testing standard.

Do not introduce Selenium as a second browser-testing framework unless there is a future requirement Playwright cannot satisfy. Maintaining duplicate browser automation stacks would increase complexity without providing current value.

## Product E2E Strategy

NEXUS should not attempt to build a complete E2E suite before product workflows exist. E2E coverage should grow with real capabilities.

Examples:

- Authentication: registration, login, logout, session expiry, permission failures.
- Conversations: start conversation, stream response, cancel generation, retry failure.
- Files / RAG: upload document, process/index, retrieve, cite source.
- Agents / tools: invoke approved action, display progress, request approval, complete or fail safely.

The majority of behavior should remain covered by faster unit, API, component, and integration tests. E2E tests should focus on critical end-user journeys and cross-system contracts.

## Real LLM Integration Testing

Real provider calls should not run on every normal pull request.

When model/provider integration matures, NEXUS should maintain controlled integration/evaluation tests that can validate:

- provider authentication and connectivity;
- request/response contract compatibility;
- streaming behavior;
- tool/function-call contract behavior where supported;
- model-specific capability assumptions;
- representative quality/evaluation scenarios.

These tests should run in a controlled workflow with explicit credentials, cost controls, deterministic fixtures where possible, and clear failure classification.

## Load and Performance Testing

Load and performance infrastructure should be introduced when meaningful production workloads exist.

Priority areas include:

- API concurrency and request latency;
- conversation streaming latency and connection stability;
- PostgreSQL and Redis behavior under expected load;
- document ingestion throughput;
- embedding and retrieval latency;
- RAG end-to-end latency;
- agent/tool/workflow execution latency;
- background-run and event-processing throughput.

Performance targets should be based on real product SLOs rather than arbitrary benchmark numbers.

## Security Testing

The existing unit/API/integration security-negative tests remain the first line of defense. Before serious production deployment, NEXUS should add dedicated security validation appropriate to its risk profile, including penetration testing and targeted assessment of authentication, authorization, tenant isolation, file handling, API security, secrets handling, tool execution, and agent boundaries.

Security testing should complement—not replace—the security-negative regression tests required during normal feature development.

## Optional Advanced Quality Tooling

SonarQube or a similar static-quality platform may be considered later if it adds useful centralized analysis beyond the existing Ruff, mypy, ESLint, TypeScript, Prettier, coverage, Playwright, Docker, and CI gates.

Mutation testing may be considered for mature, high-value domains where measuring assertion effectiveness provides enough benefit to justify the additional execution cost.

Neither capability is required simply to make NEXUS appear more enterprise-grade.

## Distributed Test Execution

Distributed or heavily parallelized test infrastructure should be introduced only when the suite is large enough that normal CI execution becomes a material delivery bottleneck.

Until then, simple deterministic CI is preferred because it is easier to understand, debug, and maintain.

## Guiding Principle

NEXUS should add quality infrastructure when there is evidence it is needed:

> Build the testing capability required by the current product and production risk. Do not build infrastructure merely because it may be useful someday.
