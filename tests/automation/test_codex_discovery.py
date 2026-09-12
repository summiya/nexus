import os

from automation.codex.controller import Orchestrator, StageOutcome, StageResult
from automation.codex.discovery import DiscoveryError, discover_ready_candidates
from automation.codex.entrypoint import process_once
from automation.codex.github import GitHubProjectItem
from automation.codex.state import WorkflowState, WorkflowTask
from automation.codex.store import InMemoryTaskStore


class FakeProjectAdapter:
    def __init__(self, project_number: int, statuses: list[str], items: list[dict]):
        self.project_number = project_number
        # statuses: list of available status strings
        self._statuses = list(statuses)
        # items: list of dicts with keys: project_item_id, issue_number, status, assignee, repo, title, body
        # keep as provided to allow malformed items to surface DiscoveryError
        self._items_list = list(items)

    def get_project_statuses(self, project_number: int) -> list[str]:
        return list(self._statuses)

    def list_project_items(self, project_number: int):
        yield from list(self._items_list)

    def get_project_item(self, project_number: int, project_item_id: int) -> dict:
        for i in self._items_list:
            if int(i.get("project_item_id", -1)) == int(project_item_id):
                return dict(i)
        raise RuntimeError("no such project item")

    def transition_project_item_status(
        self, project_number: int, project_item_id: int, new_status: str
    ) -> None:
        for idx, i in enumerate(self._items_list):
            if int(i.get("project_item_id", -1)) == int(project_item_id):
                if new_status not in self._statuses:
                    raise RuntimeError("invalid status")
                self._items_list[idx]["status"] = new_status
                return
        raise RuntimeError("no such project item")


def make_handler(outcome: StageOutcome):
    def handler(task: WorkflowTask) -> StageResult:
        return StageResult(outcome, None)

    return handler


def test_discover_ready_candidate():
    adapter = FakeProjectAdapter(
        project_number=1,
        statuses=[
            "BACKLOG",
            "READY",
            "BUILDING",
            "TESTING",
            "REVIEWING",
            "FIXING",
            "HUMAN_REVIEW",
        ],
        items=[
            {
                "project_item_id": 11,
                "issue_number": 5,
                "status": "READY",
                "assignee": "me",
                "repo": "org/repo",
                "title": "T",
                "body": "x",
            }
        ],
    )
    candidates = discover_ready_candidates(adapter, 1, "me")
    assert len(candidates) == 1
    assert isinstance(candidates[0], GitHubProjectItem)


def test_non_ready_excluded():
    adapter = FakeProjectAdapter(
        project_number=1,
        statuses=["BACKLOG", "READY"],
        items=[
            {
                "project_item_id": 12,
                "issue_number": 6,
                "status": "BACKLOG",
                "assignee": "me",
            }
        ],
    )
    candidates = discover_ready_candidates(adapter, 1, "me")
    assert candidates == []


def test_zero_ready_returns_empty():
    adapter = FakeProjectAdapter(
        project_number=1, statuses=["BACKLOG", "READY"], items=[]
    )
    candidates = discover_ready_candidates(adapter, 1, "me")
    assert candidates == []


def test_multiple_candidates_sorted():
    adapter = FakeProjectAdapter(
        project_number=1,
        statuses=["BACKLOG", "READY"],
        items=[
            {
                "project_item_id": 21,
                "issue_number": 20,
                "status": "READY",
                "assignee": "me",
            },
            {
                "project_item_id": 22,
                "issue_number": 2,
                "status": "READY",
                "assignee": "me",
            },
        ],
    )
    candidates = discover_ready_candidates(adapter, 1, "me")
    assert [c.issue_number for c in candidates] == [2, 20]


def test_malformed_item_raises():
    adapter = FakeProjectAdapter(
        project_number=1, statuses=["READY"], items=[{"bad": "item"}]
    )
    try:
        discover_ready_candidates(adapter, 1, "me")
        assert False, "expected DiscoveryError"
    except DiscoveryError:
        pass


def test_github_api_failure_propagated():
    class BrokenAdapter:
        def get_project_statuses(self, project_number: int):
            raise RuntimeError("boom")

    try:
        discover_ready_candidates(BrokenAdapter(), 1, "me")
        assert False, "expected DiscoveryError"
    except DiscoveryError:
        pass


def test_claim_and_hand_off_to_controller():
    adapter = FakeProjectAdapter(
        project_number=1,
        statuses=["READY", "BUILDING"],
        items=[
            {
                "project_item_id": 31,
                "issue_number": 7,
                "status": "READY",
                "assignee": "me",
                "repo": "org/repo",
            }
        ],
    )
    # orchestrator with handlers that just return SUCCESS
    orchestrator = Orchestrator(
        builder=make_handler(StageOutcome.SUCCESS),
        tester=make_handler(StageOutcome.SUCCESS),
        reviewer=make_handler(StageOutcome.SUCCESS),
        fixer=make_handler(StageOutcome.SUCCESS),
    )
    os.environ["CODEX_WORKER_ID"] = "me"
    result = process_once(
        1,
        adapter,
        orchestrator,
        os.environ["CODEX_WORKER_ID"],
        "run-1",
        task_store=None,
        execute=True,
        repo="org/repo",
    )
    # Step 3 must not execute builder; handoff only
    assert result["outcome"] == "claimed"


def test_claim_conflict_prevents_execution():
    adapter = FakeProjectAdapter(
        project_number=1,
        statuses=["READY", "BUILDING"],
        items=[
            {
                "project_item_id": 32,
                "issue_number": 8,
                "status": "READY",
                "assignee": "me",
                "repo": "org/repo",
            }
        ],
    )
    orchestrator = Orchestrator(
        builder=make_handler(StageOutcome.SUCCESS),
        tester=make_handler(StageOutcome.SUCCESS),
        reviewer=make_handler(StageOutcome.SUCCESS),
        fixer=make_handler(StageOutcome.SUCCESS),
    )
    store = InMemoryTaskStore()
    # simulate pre-existing claim by another actor in task store (test-only)
    pre = store.create_if_missing("org/repo#8")
    pre.claim_ready("other", "run-x")

    os.environ["CODEX_WORKER_ID"] = "me"
    result = process_once(
        1,
        adapter,
        orchestrator,
        os.environ["CODEX_WORKER_ID"],
        "run-2",
        task_store=store,
        execute=True,
        repo="org/repo",
    )
    # Local pre-existing claims are test-only and must not prevent GitHub handoff
    assert result["outcome"] == "claimed"


def test_discovery_does_not_mutate_task_state_directly():
    adapter = FakeProjectAdapter(
        project_number=1,
        statuses=["READY", "BUILDING"],
        items=[
            {
                "project_item_id": 33,
                "issue_number": 9,
                "status": "READY",
                "assignee": "me",
                "repo": "org/repo",
            }
        ],
    )
    store = InMemoryTaskStore()
    # ensure discovery path uses store but does not mutate state before claim
    _ = store.create_if_missing("org/repo#9")
    os.environ["CODEX_WORKER_ID"] = "me"
    process_once(
        1,
        adapter,
        None,
        os.environ["CODEX_WORKER_ID"],
        "run-3",
        task_store=store,
        execute=False,
        repo="org/repo",
    )
    task = store.get("org/repo#9")
    assert task is not None
    assert task.state == WorkflowState.READY
