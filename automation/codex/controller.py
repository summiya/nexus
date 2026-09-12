from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from automation.codex.state import WorkflowState, WorkflowStateError, WorkflowTask


class StageOutcome(Enum):
    SUCCESS = "SUCCESS"
    FINDING = "FINDING"
    BLOCKED = "BLOCKED"
    SPEC_GAP = "SPEC_GAP"
    INVARIANT_VIOLATION = "INVARIANT_VIOLATION"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    ERROR = "ERROR"


@dataclass
class StageResult:
    outcome: StageOutcome
    message: str | None = None


class StageHandler(Protocol):
    def __call__(
        self, task: WorkflowTask
    ) -> StageResult:  # pragma: no cover - typing only
        ...


@dataclass
class ControllerResult:
    final_state: WorkflowState
    succeeded: bool
    human_required: bool
    automation_stopped: bool
    remediation_rounds: int
    reason: str | None = None


class Orchestrator:
    """Adapter-agnostic orchestrator that drives the codex workflow state machine.

    It executes in-process handlers and never performs external I/O. Handlers
    are simple callables that receive the `WorkflowTask` and return a
    `StageResult`.
    """

    def __init__(
        self,
        builder: StageHandler,
        tester: StageHandler,
        reviewer: StageHandler,
        fixer: StageHandler,
    ) -> None:
        self.builder = builder
        self.tester = tester
        self.reviewer = reviewer
        self.fixer = fixer

    def run(self, task: WorkflowTask, claimant: str, run_id: str) -> ControllerResult:
        try:
            # Claim the READY task
            task.claim_ready(claimant, run_id)
        except WorkflowStateError as e:
            return ControllerResult(
                final_state=task.state,
                succeeded=False,
                human_required=False,
                automation_stopped=False,
                remediation_rounds=task.remediation_round,
                reason=str(e),
            )

        # BUILDING -> call builder
        builder_res = self.builder(task)
        if builder_res.outcome == StageOutcome.BLOCKED:
            return ControllerResult(
                task.state,
                False,
                False,
                False,
                task.remediation_round,
                builder_res.message,
            )
        if builder_res.outcome == StageOutcome.SPEC_GAP:
            return ControllerResult(
                task.state,
                False,
                True,
                False,
                task.remediation_round,
                builder_res.message,
            )
        if builder_res.outcome == StageOutcome.INVARIANT_VIOLATION:
            return ControllerResult(
                task.state,
                False,
                True,
                False,
                task.remediation_round,
                builder_res.message,
            )
        if builder_res.outcome != StageOutcome.SUCCESS:
            return ControllerResult(
                task.state,
                False,
                False,
                False,
                task.remediation_round,
                builder_res.message,
            )

        # Transition to TESTING
        task.transition_to(WorkflowState.TESTING)

        # TESTING -> Tester
        while True:
            tester_res = self.tester(task)
            if tester_res.outcome == StageOutcome.SUCCESS:
                # proceed to REVIEWING
                task.transition_to(WorkflowState.REVIEWING)
                break
            if tester_res.outcome == StageOutcome.FINDING:
                # route to FIXING
                task.transition_to(WorkflowState.FIXING)
                # call fixer
                fixer_res = self.fixer(task)
                if fixer_res.outcome == StageOutcome.BLOCKED:
                    return ControllerResult(
                        task.state,
                        False,
                        False,
                        False,
                        task.remediation_round,
                        fixer_res.message,
                    )
                if fixer_res.outcome == StageOutcome.HUMAN_REQUIRED:
                    return ControllerResult(
                        task.state,
                        False,
                        True,
                        False,
                        task.remediation_round,
                        fixer_res.message,
                    )
                if fixer_res.outcome == StageOutcome.INVARIANT_VIOLATION:
                    return ControllerResult(
                        task.state,
                        False,
                        True,
                        False,
                        task.remediation_round,
                        fixer_res.message,
                    )
                # After Fixer, always go back to TESTING
                if task.state == WorkflowState.AUTOMATION_STOPPED:
                    return ControllerResult(
                        task.state,
                        False,
                        False,
                        True,
                        task.remediation_round,
                        "remediation limit reached",
                    )
                task.transition_to(WorkflowState.TESTING)
                continue
            if tester_res.outcome == StageOutcome.BLOCKED:
                return ControllerResult(
                    task.state,
                    False,
                    False,
                    False,
                    task.remediation_round,
                    tester_res.message,
                )
            if tester_res.outcome == StageOutcome.HUMAN_REQUIRED:
                return ControllerResult(
                    task.state,
                    False,
                    True,
                    False,
                    task.remediation_round,
                    tester_res.message,
                )
            if tester_res.outcome == StageOutcome.INVARIANT_VIOLATION:
                return ControllerResult(
                    task.state,
                    False,
                    True,
                    False,
                    task.remediation_round,
                    tester_res.message,
                )
            # Other outcomes -> fail
            return ControllerResult(
                task.state,
                False,
                False,
                False,
                task.remediation_round,
                tester_res.message,
            )

        # REVIEWING -> Reviewer
        while True:
            reviewer_res = self.reviewer(task)
            if reviewer_res.outcome == StageOutcome.SUCCESS:
                # stop at HUMAN_REVIEW (do not auto-complete to DONE)
                task.transition_to(WorkflowState.HUMAN_REVIEW)
                return ControllerResult(
                    task.state, True, False, False, task.remediation_round, None
                )
            if reviewer_res.outcome == StageOutcome.FINDING:
                # reviewer found issues -> FIXING
                task.transition_to(WorkflowState.FIXING)
                fixer_res = self.fixer(task)
                if fixer_res.outcome == StageOutcome.BLOCKED:
                    return ControllerResult(
                        task.state,
                        False,
                        False,
                        False,
                        task.remediation_round,
                        fixer_res.message,
                    )
                if fixer_res.outcome == StageOutcome.HUMAN_REQUIRED:
                    return ControllerResult(
                        task.state,
                        False,
                        True,
                        False,
                        task.remediation_round,
                        fixer_res.message,
                    )
                if task.state == WorkflowState.AUTOMATION_STOPPED:
                    return ControllerResult(
                        task.state,
                        False,
                        False,
                        True,
                        task.remediation_round,
                        "remediation limit reached",
                    )
                # After fixing, must go through testing then reviewing again
                task.transition_to(WorkflowState.TESTING)
                # loop back to testing stage (call tester in outer loop pattern)
                # Reuse the same testing loop by calling tester here then continue
                while True:
                    tester_res = self.tester(task)
                    if tester_res.outcome == StageOutcome.SUCCESS:
                        task.transition_to(WorkflowState.REVIEWING)
                        break
                    if tester_res.outcome == StageOutcome.FINDING:
                        task.transition_to(WorkflowState.FIXING)
                        fixer_res = self.fixer(task)
                        if task.state == WorkflowState.AUTOMATION_STOPPED:
                            return ControllerResult(
                                task.state,
                                False,
                                False,
                                True,
                                task.remediation_round,
                                "remediation limit reached",
                            )
                        task.transition_to(WorkflowState.TESTING)
                        continue
                    if tester_res.outcome == StageOutcome.BLOCKED:
                        return ControllerResult(
                            task.state,
                            False,
                            False,
                            False,
                            task.remediation_round,
                            tester_res.message,
                        )
                    return ControllerResult(
                        task.state,
                        False,
                        False,
                        False,
                        task.remediation_round,
                        tester_res.message,
                    )
                # after passing tester, continue reviewer loop
                continue
            if reviewer_res.outcome == StageOutcome.BLOCKED:
                return ControllerResult(
                    task.state,
                    False,
                    False,
                    False,
                    task.remediation_round,
                    reviewer_res.message,
                )
            if reviewer_res.outcome == StageOutcome.HUMAN_REQUIRED:
                return ControllerResult(
                    task.state,
                    False,
                    True,
                    False,
                    task.remediation_round,
                    reviewer_res.message,
                )
            if reviewer_res.outcome == StageOutcome.INVARIANT_VIOLATION:
                return ControllerResult(
                    task.state,
                    False,
                    True,
                    False,
                    task.remediation_round,
                    reviewer_res.message,
                )
            return ControllerResult(
                task.state,
                False,
                False,
                False,
                task.remediation_round,
                reviewer_res.message,
            )


__all__ = [
    "ControllerResult",
    "Orchestrator",
    "StageHandler",
    "StageOutcome",
    "StageResult",
]
