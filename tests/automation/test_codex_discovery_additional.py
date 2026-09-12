import os

from automation.codex.discovery import discover_ready_candidates
from automation.codex.entrypoint import process_once


class AdapterWithDifferentGet:
    """Simulate item that appears READY in list but has changed when fetched."""

    def __init__(
        self,
        project_number: int,
        list_item: dict,
        get_item: dict,
        statuses: list[str] | None = None,
    ):
        self._list_item = dict(list_item)
        self._get_item = dict(get_item)
        self._statuses = list(statuses or ["BACKLOG", "READY", "BUILDING"])

    def get_project_statuses(self, project_number: int) -> list[str]:
        return list(self._statuses)

    def list_project_items(self, project_number: int):
        yield dict(self._list_item)

    def get_project_item(self, project_number: int, project_item_id: int) -> dict:
        return dict(self._get_item)

    def transition_project_item_status(
        self, project_number: int, project_item_id: int, new_status: str
    ) -> None:
        # for tests we can accept transitions
        self._get_item["status"] = new_status


def test_unassigned_ready_ignored():
    from tests.automation.test_codex_discovery import FakeProjectAdapter

    adapter = FakeProjectAdapter(
        project_number=1,
        statuses=["BACKLOG", "READY"],
        items=[
            {
                "project_item_id": 41,
                "issue_number": 10,
                "status": "READY",
                "assignee": None,
            }
        ],
    )
    candidates = discover_ready_candidates(adapter, 1, "me")
    assert candidates == []


def test_ready_assigned_to_other_ignored():
    from tests.automation.test_codex_discovery import FakeProjectAdapter

    adapter = FakeProjectAdapter(
        project_number=1,
        statuses=["BACKLOG", "READY"],
        items=[
            {
                "project_item_id": 42,
                "issue_number": 11,
                "status": "READY",
                "assignee": "other",
            }
        ],
    )
    candidates = discover_ready_candidates(adapter, 1, "me")
    assert candidates == []


def test_non_ready_assigned_to_worker_ignored():
    from tests.automation.test_codex_discovery import FakeProjectAdapter

    adapter = FakeProjectAdapter(
        project_number=1,
        statuses=["BACKLOG", "READY"],
        items=[
            {
                "project_item_id": 43,
                "issue_number": 12,
                "status": "BACKLOG",
                "assignee": "me",
            }
        ],
    )
    candidates = discover_ready_candidates(adapter, 1, "me")
    assert candidates == []


def test_missing_worker_env_returns_config_error():
    adapter = AdapterWithDifferentGet(
        1,
        {
            "project_item_id": 44,
            "issue_number": 13,
            "status": "READY",
            "assignee": "me",
        },
        {
            "project_item_id": 44,
            "issue_number": 13,
            "status": "READY",
            "assignee": "me",
        },
    )
    # clear env
    if "CODEX_WORKER_ID" in os.environ:
        del os.environ["CODEX_WORKER_ID"]
    res = process_once(
        1,
        adapter,
        None,
        claimant=None,
        run_id="r",
        task_store=None,
        execute=False,
        repo=None,
    )
    assert res["outcome"] == "config_error"


def test_stale_status_prevents_execution():
    # list shows READY assigned to me, but get_project_item shows status changed
    list_item = {
        "project_item_id": 45,
        "issue_number": 14,
        "status": "READY",
        "assignee": "me",
        "repo": "org/repo",
    }
    get_item = {
        "project_item_id": 45,
        "issue_number": 14,
        "status": "BACKLOG",
        "assignee": "me",
        "repo": "org/repo",
    }
    adapter = AdapterWithDifferentGet(1, list_item, get_item)
    os.environ["CODEX_WORKER_ID"] = "me"
    res = process_once(
        1,
        adapter,
        None,
        os.environ["CODEX_WORKER_ID"],
        "run-x",
        task_store=None,
        execute=True,
        repo="org/repo",
    )
    assert res["outcome"] == "stale"


def test_stale_assignee_prevents_execution():
    list_item = {
        "project_item_id": 46,
        "issue_number": 15,
        "status": "READY",
        "assignee": "me",
        "repo": "org/repo",
    }
    get_item = {
        "project_item_id": 46,
        "issue_number": 15,
        "status": "READY",
        "assignee": "other",
        "repo": "org/repo",
    }
    adapter = AdapterWithDifferentGet(1, list_item, get_item)
    os.environ["CODEX_WORKER_ID"] = "me"
    res = process_once(
        1,
        adapter,
        None,
        os.environ["CODEX_WORKER_ID"],
        "run-x",
        task_store=None,
        execute=True,
        repo="org/repo",
    )
    assert res["outcome"] == "stale"


def test_worker_active_task_prevents_start():
    from tests.automation.test_codex_discovery import FakeProjectAdapter

    adapter = FakeProjectAdapter(
        project_number=1,
        statuses=["READY", "BUILDING"],
        items=[
            {
                "project_item_id": 47,
                "issue_number": 16,
                "status": "BUILDING",
                "assignee": "me",
                "repo": "org/repo",
            },
            {
                "project_item_id": 48,
                "issue_number": 17,
                "status": "READY",
                "assignee": "me",
                "repo": "org/repo",
            },
        ],
    )
    os.environ["CODEX_WORKER_ID"] = "me"
    res = process_once(
        1,
        adapter,
        None,
        os.environ["CODEX_WORKER_ID"],
        "run-y",
        task_store=None,
        execute=False,
        repo="org/repo",
    )
    assert res["outcome"] == "already_active"
