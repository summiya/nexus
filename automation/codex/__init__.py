"""Automation: Codex orchestration domain primitives.

This package contains deterministic, repository-local domain logic for the
Codex engineering orchestration state machine and claim semantics. It is
intentionally separated from the `src/nexus` application code and contains no
external persistence or GitHub-specific adapters.
"""

__all__ = ["state"]
