from automation.codex.controller import Orchestrator, StageOutcome, StageResult
from automation.codex.state import WorkflowState, WorkflowTask


def make_handler(outcome: StageOutcome, message: str | None = None):
    def handler(task: WorkflowTask) -> StageResult:
        return StageResult(outcome, message)

    return handler


def test_normal_flow():
    task = WorkflowTask("C1", state=WorkflowState.READY)
    orchestrator = Orchestrator(
        builder=make_handler(StageOutcome.SUCCESS),
        tester=make_handler(StageOutcome.SUCCESS),
        reviewer=make_handler(StageOutcome.SUCCESS),
        fixer=make_handler(StageOutcome.SUCCESS),
    )
    result = orchestrator.run(task, "bldr", "run-1")
    assert result.succeeded
    assert result.final_state == WorkflowState.HUMAN_REVIEW


def test_tester_finding_triggers_fixing_then_testing():
    # tester first returns FINDING, then SUCCESS after fixer
    calls = {"tester": 0}

    def tester(task: WorkflowTask):
        calls["tester"] += 1
        if calls["tester"] == 1:
            return StageResult(StageOutcome.FINDING, "failed tests")
        return StageResult(StageOutcome.SUCCESS)

    orchestrator = Orchestrator(
        builder=make_handler(StageOutcome.SUCCESS),
        tester=tester,
        reviewer=make_handler(StageOutcome.SUCCESS),
        fixer=make_handler(StageOutcome.SUCCESS),
    )
    task = WorkflowTask("C2", state=WorkflowState.READY)
    result = orchestrator.run(task, "bldr", "run-2")
    assert result.succeeded
    assert result.remediation_rounds == 1


def test_reviewer_finding_triggers_fixing_and_retest():
    # reviewer returns FINDING on first call
    calls = {"reviewer": 0}

    def reviewer(task: WorkflowTask):
        calls["reviewer"] += 1
        if calls["reviewer"] == 1:
            return StageResult(StageOutcome.FINDING, "style issue")
        return StageResult(StageOutcome.SUCCESS)

    orchestrator = Orchestrator(
        builder=make_handler(StageOutcome.SUCCESS),
        tester=make_handler(StageOutcome.SUCCESS),
        reviewer=reviewer,
        fixer=make_handler(StageOutcome.SUCCESS),
    )
    task = WorkflowTask("C3", state=WorkflowState.READY)
    result = orchestrator.run(task, "bldr", "run-3")
    assert result.succeeded
    assert task.remediation_round == 1


def test_remediation_limit_stops_automation():
    # tester always returns FINDING so remediation increments each loop
    def tester(task: WorkflowTask):
        return StageResult(StageOutcome.FINDING, "always failing")

    orchestrator = Orchestrator(
        builder=make_handler(StageOutcome.SUCCESS),
        tester=tester,
        reviewer=make_handler(StageOutcome.SUCCESS),
        fixer=make_handler(StageOutcome.SUCCESS),
    )
    task = WorkflowTask("C4", state=WorkflowState.READY)
    result = orchestrator.run(task, "bldr", "run-4")
    assert not result.succeeded
    assert result.automation_stopped


def test_claim_conflict_is_reported():
    task = WorkflowTask("C5", state=WorkflowState.READY)
    # Pre-claim by another
    task.claim_ready("other", "run-x")
    orchestrator = Orchestrator(
        builder=make_handler(StageOutcome.SUCCESS),
        tester=make_handler(StageOutcome.SUCCESS),
        reviewer=make_handler(StageOutcome.SUCCESS),
        fixer=make_handler(StageOutcome.SUCCESS),
    )
    result = orchestrator.run(task, "bldr", "run-5")
    assert not result.succeeded
    # The claim API rejects non-READY tasks; when a task was already
    # claimed previously it will no longer be READY and the contract is to
    # report that it is not READY and cannot be newly claimed.
    reason = (result.reason or "").lower()
    assert "not ready" in reason
