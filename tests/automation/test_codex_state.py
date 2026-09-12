import pytest

from automation.codex.state import (
    WorkflowState,
    WorkflowStateError,
    WorkflowTask,
    is_valid_transition,
)


def test_valid_transitions() -> None:
    assert is_valid_transition(WorkflowState.BACKLOG, WorkflowState.READY)
    assert is_valid_transition(WorkflowState.READY, WorkflowState.BUILDING)
    assert is_valid_transition(WorkflowState.BUILDING, WorkflowState.TESTING)
    assert is_valid_transition(WorkflowState.TESTING, WorkflowState.REVIEWING)
    assert is_valid_transition(WorkflowState.REVIEWING, WorkflowState.HUMAN_REVIEW)


def test_invalid_transition_rejected() -> None:
    task = WorkflowTask(task_id="T1", state=WorkflowState.READY)
    with pytest.raises(WorkflowStateError):
        task.transition_to(WorkflowState.DONE)


def test_ready_to_building_claim() -> None:
    task = WorkflowTask(task_id="T2", state=WorkflowState.READY)
    task.claim_ready("builder-1", "run-1")
    assert task.state == WorkflowState.BUILDING
    assert task.owner == "builder-1"
    assert task.run_id == "run-1"
    assert task.claim_id == "run-1"


def test_duplicate_claim_rejected() -> None:
    task = WorkflowTask(task_id="T3", state=WorkflowState.READY)
    task.claim_ready("builder-1", "run-1")
    with pytest.raises(WorkflowStateError):
        task.claim_ready("builder-2", "run-2")


def test_same_claim_id_idempotent() -> None:
    task = WorkflowTask(task_id="T4", state=WorkflowState.READY)
    task.claim_ready("builder-1", "run-1")
    # retry same claimant/run should be ok
    task.claim_ready("builder-1", "run-1")
    assert task.owner == "builder-1"


def test_non_ready_cannot_be_claimed() -> None:
    task = WorkflowTask(task_id="T5", state=WorkflowState.BACKLOG)
    with pytest.raises(WorkflowStateError):
        task.claim_ready("builder-1", "run-1")


def test_remediation_rounds_and_stopping() -> None:
    task = WorkflowTask(task_id="T6", state=WorkflowState.TESTING)
    # Round 1
    task.transition_to(WorkflowState.FIXING)
    assert task.remediation_round == 1
    # Back to testing, then fixing again
    task.transition_to(WorkflowState.TESTING)
    task.transition_to(WorkflowState.FIXING)
    assert task.remediation_round == 2
    # Third round
    task.transition_to(WorkflowState.TESTING)
    task.transition_to(WorkflowState.FIXING)
    assert task.remediation_round == 3
    # Fourth attempt should move to AUTOMATION_STOPPED
    task.transition_to(WorkflowState.TESTING)
    task.transition_to(WorkflowState.FIXING)
    assert task.state == WorkflowState.AUTOMATION_STOPPED


def test_blocked_and_terminal_states() -> None:
    task = WorkflowTask(task_id="T7", state=WorkflowState.BUILDING)
    task.transition_to(WorkflowState.BLOCKED, reason="waiting")
    assert task.state == WorkflowState.BLOCKED
    # From blocked we can go back to READY
    task.transition_to(WorkflowState.READY)
    assert task.state == WorkflowState.READY
