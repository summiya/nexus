from __future__ import annotations

import argparse
import os

from automation.codex.controller import Orchestrator
from automation.codex.discovery import (
    DiscoveryError,
    discover_ready_candidates,
    worker_has_active_task,
)
from automation.codex.github import GitHubAPI, build_graphql_api
from automation.codex.state import WorkflowState, WorkflowTask
from automation.codex.store import InMemoryTaskStore


def process_once(
    project_number: int,
    api: GitHubAPI,
    orchestrator: Orchestrator | None,
    claimant: str,
    run_id: str,
    task_store: InMemoryTaskStore | None = None,
    execute: bool = False,
    repo: str | None = None,
):
    """Discover READY candidates and attempt to claim/hand-off one.

    Returns a dict with explicit outcome information. If `execute=True`, this
    function will perform the authoritative GitHub READY -> BUILDING mutation
    as the handoff. When `execute=False` the function is discovery-only and
    performs zero GitHub mutations.
    """
    # claimant parameter is preserved for library/test usage. In production
    # execution the wrapper must pass the authoritative CODEX_WORKER_ID as
    # `claimant` (do NOT rely on CODER_CLAIMANT or a default like codex-bot).
    worker_id = claimant or os.getenv("CODEX_WORKER_ID")
    if not worker_id:
        return {"outcome": "config_error", "reason": "CODEX_WORKER_ID not set"}

    try:
        # ensure worker has no active task
        if worker_has_active_task(api, project_number, worker_id):
            return {"outcome": "already_active", "worker_id": worker_id}
    except DiscoveryError as e:
        return {"outcome": "github_error", "reason": str(e)}

    try:
        candidates = discover_ready_candidates(api, project_number, worker_id)
    except DiscoveryError as e:
        return {"outcome": "github_error", "reason": str(e)}

    if not candidates:
        return {"outcome": "no_candidates"}

    cand = candidates[0]
    # Determine repo for task id: explicit param, project item repo, or env GITHUB_REPOSITORY
    chosen_repo = repo or cand.repo or os.getenv("GITHUB_REPOSITORY")
    task_id = f"{chosen_repo or project_number}#{cand.issue_number}"

    # discovery-only; do not perform handoff
    if not execute:
        return {"outcome": "candidate", "task_id": task_id}

    # Verify current project item state and assignee before attempting handoff
    try:
        current = api.get_project_item(project_number, cand.project_item_id)
    except RuntimeError as e:
        return {"outcome": "github_error", "reason": str(e)}

    if str(current.get("status")).upper() != "READY":
        return {"outcome": "stale", "reason": "project item not READY"}
    if str(current.get("assignee")) != worker_id:
        return {"outcome": "stale", "reason": "assignee changed"}

    # Ensure BUILDING status exists
    try:
        statuses = api.get_project_statuses(project_number)
    except RuntimeError as e:
        return {"outcome": "github_error", "reason": str(e)}
    if "BUILDING" not in [s.upper() for s in statuses]:
        return {"outcome": "config_error", "reason": "BUILDING status not in project"}

    # Transition project status to BUILDING as explicit handoff (GitHub is the
    # authoritative ownership boundary). Do not perform a second local claim
    # that could invalidate a successful GitHub handoff.
    try:
        api.transition_project_item_status(
            project_number, cand.project_item_id, "BUILDING"
        )
    except RuntimeError as e:
        return {"outcome": "github_error", "reason": str(e)}

    # Record the task locally for internal workflow tracking if a test store is
    # provided, but do NOT use it as the cross-machine claim mechanism. The
    # GitHub transition above is the single ownership change.
    if task_store is not None:
        task_store.create_if_missing(task_id)
    else:
        # transient local representation only
        _ = WorkflowTask(task_id=task_id, state=WorkflowState.READY)

    # Handoff succeeded; do not execute builder/tester/reviewer/fixer in Step 3
    # — the purpose here is discovery/routing and explicit GitHub handoff only.
    return {"outcome": "claimed", "task_id": task_id}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument(
        "--claimant",
        default=None,
        help="Optional claimant for tests; production uses CODEX_WORKER_ID env",
    )
    parser.add_argument("--run-id", default=os.getenv("CODER_RUN_ID", "run-local"))
    parser.add_argument(
        "--execute",
        action="store_true",
        help="If set, perform READY -> BUILDING handoff",
    )
    _args = parser.parse_args(argv)

    # If executing (production mode), construct the GraphQL adapter from
    # environment and validate required configuration. This wrapper follows
    # production rules: authoritative worker identity comes from
    # `CODEX_WORKER_ID` env and `GITHUB_PROJECT_NUMBER` must be set and a
    # positive integer.
    if _args.execute:
        # Validate worker identity
        worker_id = os.getenv("CODEX_WORKER_ID")
        if not worker_id:
            print("ERROR: CODEX_WORKER_ID not set", flush=True)
            raise SystemExit(2)

        # Validate GitHub repository and token
        gh_repo = os.getenv("GITHUB_REPOSITORY")
        gh_token = os.getenv("GITHUB_TOKEN")
        if not gh_repo:
            print("ERROR: GITHUB_REPOSITORY not set", flush=True)
            raise SystemExit(2)
        if not gh_token:
            print("ERROR: GITHUB_TOKEN not set", flush=True)
            raise SystemExit(2)

        # Validate project number
        proj_raw = os.getenv("GITHUB_PROJECT_NUMBER")
        if not proj_raw:
            print("ERROR: GITHUB_PROJECT_NUMBER not set", flush=True)
            raise SystemExit(2)
        try:
            project_number = int(proj_raw)
            if project_number <= 0:
                raise ValueError()
        except ValueError:
            print("ERROR: GITHUB_PROJECT_NUMBER must be a positive integer", flush=True)
            raise SystemExit(2)

        # Construct production GraphQL adapter (delegated to github helper)
        api = build_graphql_api(repository=gh_repo, token=gh_token)

        # Run with authoritative worker identity from env (do not use --claimant)
        result = process_once(
            project_number=project_number,
            api=api,
            orchestrator=None,
            claimant=worker_id,
            run_id=_args.run_id,
            task_store=None,
            execute=True,
            repo=_args.repo,
        )
        print(result)
        return (
            0
            if result.get("outcome") in ("claimed", "candidate", "no_candidates")
            else 1
        )

    # Discovery-only mode: do not perform GitHub mutations. Use provided
    # claimant (useful for tests) or fall back to CODEX_WORKER_ID if set.
    claimant = _args.claimant or os.getenv("CODEX_WORKER_ID")
    # project_number may be passed via env for discovery too; try to parse if present
    proj_raw = os.getenv("GITHUB_PROJECT_NUMBER")
    project_number = int(proj_raw) if proj_raw and proj_raw.isdigit() else 0

    # For discovery-only runs we require a GitHub API implementation; tests
    # typically inject a fake adapter. Here we construct a GraphQL adapter if
    # environment provides credentials; otherwise we error out to avoid silent
    # misconfiguration.
    api: GitHubAPI
    gh_repo = os.getenv("GITHUB_REPOSITORY")
    gh_token = os.getenv("GITHUB_TOKEN")
    if gh_repo and gh_token:
        api = build_graphql_api(repository=gh_repo, token=gh_token)
    else:
        print(
            "ERROR: discovery mode requires GITHUB_REPOSITORY and GITHUB_TOKEN in env or a test adapter",
            flush=True,
        )
        raise SystemExit(2)

    # If a valid project_number env var was provided, use it; otherwise fail
    if not project_number:
        print(
            "ERROR: GITHUB_PROJECT_NUMBER not set or invalid for discovery", flush=True
        )
        raise SystemExit(2)

    result = process_once(
        project_number=project_number,
        api=api,
        orchestrator=None,
        claimant=claimant,
        run_id=_args.run_id,
        task_store=None,
        execute=False,
        repo=_args.repo,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(
        "The entrypoint is intended to be invoked by a wrapper that provides a GitHubAPI implementation."
    )


__all__ = ["main", "process_once"]
