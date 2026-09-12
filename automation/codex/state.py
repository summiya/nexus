from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class WorkflowStateError(RuntimeError):
    """Raised when a state transition or claim is invalid."""


class WorkflowState(str, Enum):
    BACKLOG = "BACKLOG"
    READY = "READY"
    BUILDING = "BUILDING"
    TESTING = "TESTING"
    REVIEWING = "REVIEWING"
    FIXING = "FIXING"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    BLOCKED = "BLOCKED"
    AUTOMATION_STOPPED = "AUTOMATION_STOPPED"
    DONE = "DONE"

    @staticmethod
    def coerce(value: WorkflowState | str) -> WorkflowState:
        if isinstance(value, WorkflowState):
            return value
        if isinstance(value, str):
            normalized = value.strip().upper().replace(" ", "_")
            for candidate in WorkflowState:
                if candidate.name == normalized or candidate.value == normalized:
                    return candidate
        raise WorkflowStateError(f"Unknown workflow state: {value!r}")


_VALID_TRANSITIONS: dict[WorkflowState, set[WorkflowState]] = {
    WorkflowState.BACKLOG: {WorkflowState.READY, WorkflowState.BLOCKED},
    WorkflowState.READY: {WorkflowState.BUILDING, WorkflowState.BLOCKED},
    WorkflowState.BUILDING: {WorkflowState.TESTING, WorkflowState.BLOCKED, WorkflowState.FIXING},
    WorkflowState.TESTING: {WorkflowState.REVIEWING, WorkflowState.FIXING, WorkflowState.BLOCKED},
    WorkflowState.REVIEWING: {WorkflowState.HUMAN_REVIEW, WorkflowState.FIXING, WorkflowState.BLOCKED},
    WorkflowState.FIXING: {WorkflowState.TESTING, WorkflowState.AUTOMATION_STOPPED, WorkflowState.BLOCKED},
    WorkflowState.HUMAN_REVIEW: {WorkflowState.DONE, WorkflowState.BLOCKED, WorkflowState.READY},
    WorkflowState.BLOCKED: {WorkflowState.READY, WorkflowState.AUTOMATION_STOPPED},
    WorkflowState.AUTOMATION_STOPPED: set(),
    WorkflowState.DONE: set(),
}


def is_valid_transition(from_state: WorkflowState | str, to_state: WorkflowState | str) -> bool:
    src = WorkflowState.coerce(from_state)
    tgt = WorkflowState.coerce(to_state)
    return tgt in _VALID_TRANSITIONS.get(src, set())


@dataclass
class WorkflowTask:
    task_id: str
    state: WorkflowState = WorkflowState.BACKLOG
    owner: str | None = None
    run_id: str | None = None
    claim_id: str | None = None
    remediation_round: int = 0
    branch_name: str | None = None
    pr_number: int | None = None
    failure_reason: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    MAX_REMEDIATION_ROUNDS: int = 3

    def transition_to(self, next_state: WorkflowState | str, *, reason: str | None = None) -> WorkflowTask:
        target = WorkflowState.coerce(next_state)

        if not is_valid_transition(self.state, target):
            raise WorkflowStateError(f"Invalid transition: {self.state.value} -> {target.value}")

        # Remediation logic: entering FIXING increments remediation counter.
        if target == WorkflowState.FIXING:
            # If already exhausted, move to AUTOMATION_STOPPED instead of FIXING
            if self.remediation_round >= self.MAX_REMEDIATION_ROUNDS:
                self.state = WorkflowState.AUTOMATION_STOPPED
                self.failure_reason = "remediation limit reached"
                self.updated_at = datetime.now(UTC)
                return self
            self.remediation_round += 1

        self.state = target
        if reason:
            self.failure_reason = reason
        self.updated_at = datetime.now(UTC)
        return self

    def claim_ready(self, claimant: str, run_id: str) -> WorkflowTask:
        if not claimant:
            raise WorkflowStateError("claimant required")
        if not run_id:
            raise WorkflowStateError("run_id required")

        # Only a task in READY may be newly claimed
        if self.state == WorkflowState.READY:
            if self.owner is None:
                # Accept claim
                self.owner = claimant
                self.run_id = run_id
                self.claim_id = run_id
                # Transition to BUILDING
                return self.transition_to(WorkflowState.BUILDING, reason=f"claimed by {claimant}")
            # if owner present
            if self.owner == claimant and self.run_id == run_id:
                # idempotent retry: re-affirm claim
                self.updated_at = datetime.now(UTC)
                return self
            # already claimed by someone else
            raise WorkflowStateError(f"task {self.task_id} already claimed by {self.owner}")

        # If already BUILDING and matches claimant/run -> idempotent
        if self.state == WorkflowState.BUILDING and self.owner == claimant and self.run_id == run_id:
            self.updated_at = datetime.now(UTC)
            return self

        raise WorkflowStateError(f"task {self.task_id} is not READY and cannot be newly claimed")

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "state": self.state.value,
            "owner": self.owner,
            "run_id": self.run_id,
            "claim_id": self.claim_id,
            "remediation_round": self.remediation_round,
            "branch_name": self.branch_name,
            "pr_number": self.pr_number,
            "failure_reason": self.failure_reason,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


__all__ = ["WorkflowState", "WorkflowStateError", "WorkflowTask", "is_valid_transition"]
