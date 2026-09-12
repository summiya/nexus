from __future__ import annotations

from automation.codex.github import GitHubAPI, GitHubProjectItem


class DiscoveryError(RuntimeError):
    pass


ACTIVE_STATUSES = {"BUILDING", "TESTING", "REVIEWING", "FIXING", "HUMAN_REVIEW"}


def discover_ready_candidates(api: GitHubAPI, project_number: int, worker_id: str) -> list[GitHubProjectItem]:
    """Discover project items that are in Project Status == READY and assigned to `worker_id`.

    This function is side-effect free. It validates that the project contains a
    `READY` status option and then returns deterministic candidates sorted by
    issue number.
    """
    try:
        statuses = api.get_project_statuses(project_number)
    except Exception as e:
        raise DiscoveryError(f"GitHub API failure: {e}") from e

    # Ensure READY status exists in the project
    normalized = [s.upper() for s in statuses]
    if "READY" not in normalized:
        raise DiscoveryError("Project does not expose READY status")

    try:
        items = list(api.list_project_items(project_number))
    except Exception as e:
        raise DiscoveryError(f"GitHub API failure: {e}") from e

    candidates: list[GitHubProjectItem] = []
    for raw in items:
        if not isinstance(raw, dict):
            raise DiscoveryError("malformed project item: expected mapping")
        if "issue_number" not in raw or "project_item_id" not in raw:
            raise DiscoveryError("malformed project item: missing fields")

        status = raw.get("status")
        assignee = raw.get("assignee")

        if not status or str(status).upper() != "READY":
            continue
        if not assignee or str(assignee) != worker_id:
            continue

        candidates.append(
            GitHubProjectItem(
                project_number=project_number,
                project_item_id=int(raw["project_item_id"]),
                issue_number=int(raw["issue_number"]),
                repo=raw.get("repo"),
                status=str(status),
                assignee=str(assignee),
                title=raw.get("title"),
                body=raw.get("body"),
            )
        )

    # Deterministic ordering by issue number
    candidates.sort(key=lambda c: c.issue_number)
    return candidates


def worker_has_active_task(api: GitHubAPI, project_number: int, worker_id: str) -> bool:
    try:
        items = list(api.list_project_items(project_number))
    except Exception as e:
        raise DiscoveryError(f"GitHub API failure: {e}") from e

    for raw in items:
        if not isinstance(raw, dict):
            continue
        status = raw.get("status")
        assignee = raw.get("assignee")
        if not status or not assignee:
            continue
        if str(assignee) == worker_id and str(status).upper() in ACTIVE_STATUSES:
            return True
    return False


__all__ = ["DiscoveryError", "discover_ready_candidates", "worker_has_active_task"]
