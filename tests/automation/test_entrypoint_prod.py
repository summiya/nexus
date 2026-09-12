import os

import pytest

from automation.codex import entrypoint


class FakeAPI:
    def __init__(self, *a, **kw):
        self.transition_called = False

    def get_project_statuses(self, project_number: int):
        return ["READY", "BUILDING"]

    def list_project_items(self, project_number: int):
        return [
            {
                "project_item_id": 1,
                "issue_number": 10,
                "status": "READY",
                "assignee": "worker1",
                "repo": "s/repo",
            }
        ]

    def get_project_item(self, project_number: int, project_item_id: int):
        return {"project_item_id": project_item_id, "status": "READY", "assignee": "worker1"}

    def transition_project_item_status(self, project_number: int, project_item_id: int, new_status: str):
        self.transition_called = True


def test_process_once_discovery_does_not_mutate():
    api = FakeAPI()
    res = entrypoint.process_once(
        project_number=1,
        api=api,
        orchestrator=None,
        claimant="worker1",
        run_id="r",
        task_store=None,
        execute=False,
        repo="s/repo",
    )
    assert res["outcome"] == "candidate"
    assert not api.transition_called


def test_process_once_execute_performs_transition():
    api = FakeAPI()
    res = entrypoint.process_once(
        project_number=1,
        api=api,
        orchestrator=None,
        claimant="worker1",
        run_id="r",
        task_store=None,
        execute=True,
        repo="s/repo",
    )
    assert res["outcome"] == "claimed"
    assert api.transition_called


def test_main_constructs_graphql_and_passes_authoritative_worker(monkeypatch):
    os.environ["GITHUB_REPOSITORY"] = "owner/repo"
    os.environ["GITHUB_TOKEN"] = "t"
    os.environ["GITHUB_PROJECT_NUMBER"] = "1"
    os.environ["CODEX_WORKER_ID"] = "envworker"

    constructed = {}

    def fake_ctor(*a, **kw):
        constructed["called"] = True
        constructed["args"] = a
        constructed["kw"] = kw
        return FakeAPI()

    called = {}

    def fake_process_once(*a, **k):
        called["args"] = a
        called["kwargs"] = k
        return {"outcome": "claimed"}

    monkeypatch.setattr(entrypoint, "GraphQLGitHubAPI", fake_ctor)
    monkeypatch.setattr(entrypoint, "process_once", fake_process_once)

    rc = entrypoint.main(["--repo", "owner/repo", "--execute"])
    assert rc == 0
    assert constructed.get("called")
    # claimant passed to process_once should be CODEX_WORKER_ID
    assert called.get("kwargs")["claimant"] == "envworker"


def test_main_missing_project_number_fails(monkeypatch):
    os.environ["GITHUB_REPOSITORY"] = "owner/repo"
    os.environ["GITHUB_TOKEN"] = "t"
    if "GITHUB_PROJECT_NUMBER" in os.environ:
        del os.environ["GITHUB_PROJECT_NUMBER"]
    os.environ["CODEX_WORKER_ID"] = "envworker"

    with pytest.raises(SystemExit) as e:
        entrypoint.main(["--repo", "owner/repo", "--execute"])
    assert e.value.code == 2


def test_main_invalid_project_number_fails(monkeypatch):
    os.environ["GITHUB_REPOSITORY"] = "owner/repo"
    os.environ["GITHUB_TOKEN"] = "t"
    os.environ["GITHUB_PROJECT_NUMBER"] = "0"
    os.environ["CODEX_WORKER_ID"] = "envworker"

    with pytest.raises(SystemExit) as e:
        entrypoint.main(["--repo", "owner/repo", "--execute"])
    assert e.value.code == 2
