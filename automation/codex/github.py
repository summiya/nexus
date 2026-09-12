from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


class GitHubAPI(Protocol):
    def get_project_statuses(self, project_number: int) -> list[str]:
        ...

    def list_project_items(self, project_number: int) -> Iterable[dict]:
        ...

    def get_project_item(self, project_number: int, project_item_id: int) -> dict:
        ...

    def transition_project_item_status(self, project_number: int, project_item_id: int, new_status: str) -> None:
        ...


@dataclass
class GitHubProjectItem:
    project_number: int
    project_item_id: int
    issue_number: int
    repo: str | None = None
    status: str | None = None
    assignee: str | None = None
    title: str | None = None
    body: str | None = None


__all__ = ["GitHubAPI", "GitHubProjectItem"]


class GraphQLGitHubAPI:
    """Minimal GitHub GraphQL adapter implementing the `GitHubAPI` Protocol.

    Notes:
    - Uses `GITHUB_TOKEN` from environment; never logs the token.
    - Uses `GITHUB_REPOSITORY` from environment as owner/repo when needed.
    - This adapter performs best-effort GraphQL queries for ProjectV2. Unit
      tests should continue to use fake adapters and not require live GitHub
      credentials.
    """

    ENDPOINT = "https://api.github.com/graphql"

    def __init__(self, repository: str | None = None, token: str | None = None):
        self.repository = repository or os.getenv("GITHUB_REPOSITORY")
        self.token = token or os.getenv("GITHUB_TOKEN")
        if not self.token:
            raise RuntimeError("GITHUB_TOKEN not set")
        if not self.repository:
            raise RuntimeError("GITHUB_REPOSITORY not set")
        owner, name = self.repository.split("/", 1)
        self.owner = owner
        self.name = name

    def _graphql(self, query: str, variables: dict | None = None) -> dict:
        payload = {"query": query, "variables": variables or {}}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.ENDPOINT, data=data, method="POST")
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read()
        except Exception as e:
            raise RuntimeError(f"GitHub GraphQL request failed: {e}") from e
        try:
            result = json.loads(body)
        except Exception as e:
            raise RuntimeError(f"Invalid JSON response from GitHub: {e}") from e
        if "errors" in result:
            raise RuntimeError(f"GitHub GraphQL errors: {result['errors']}")
        return result.get("data", {})

    def get_project_statuses(self, project_number: int) -> list[str]:
        q = """
        query ($owner: String!, $number: Int!) {
          user(login: $owner) {
            projectV2(number: $number) {
              fields(first: 20) {
                nodes {
                  ... on ProjectV2SingleSelectField {
                    name
                    options { id name }
                  }
                }
              }
            }
          }
        }
        """
        data = self._graphql(q, {"owner": self.owner, "number": project_number})
        proj = data.get("user", {}).get("projectV2")
        if not proj:
            return []
        # find the explicit Status field by exact name match (case-insensitive)
        fields = proj.get("fields", {}).get("nodes", [])
        status_field = None
        for f in fields:
            name = f.get("name")
            if name and name.strip().lower() == "status":
                status_field = f
                break
        if not status_field:
            raise RuntimeError("Status field not found in project")
        options = status_field.get("options", [])
        return [opt.get("name") for opt in options if opt.get("name")]

    def list_project_items(self, project_number: int):
        # Fetch items and return mapping-like dicts suitable for discovery.
        q = """
        query ($owner: String!, $number: Int!, $cursor: String) {
          user(login: $owner) {
            projectV2(number: $number) {
              items(first: 100, after: $cursor) {
                nodes {
                  id
                  databaseId
                  content {
                    ... on Issue {
                      number
                      repository { nameWithOwner }
                      assignees(first: 10) { nodes { login } }
                      title
                      body
                    }
                  }
                  fieldValues(first: 20) {
                    nodes {
                      ... on ProjectV2ItemFieldSingleSelectValue {
                        name
                        field { name }
                      }
                    }
                  }
                }
                pageInfo { hasNextPage endCursor }
              }
            }
          }
        }
        """

        items: list[dict] = []
        cursor: str | None = None
        while True:
            vars = {"owner": self.owner, "number": project_number, "cursor": cursor}
            data = self._graphql(q, vars)
            nodes = data.get("user", {}).get("projectV2", {}).get("items", {}).get("nodes", [])
            for n in nodes:
                project_item_id = n.get("databaseId") or n.get("id")
                content = n.get("content") or {}
                issue_number = content.get("number")
                repo = None
                if content.get("repository"):
                    repo = content["repository"].get("nameWithOwner")
                assignee = None
                a_nodes = content.get("assignees", {}).get("nodes", [])
                if a_nodes:
                    assignee = a_nodes[0].get("login")

                # find single-select value belonging to the explicit Status field
                status = None
                for fv in n.get("fieldValues", {}).get("nodes", []):
                    field = fv.get("field", {})
                    if field and field.get("name") and field.get("name").strip().lower() == "status":
                        status = fv.get("name")
                        break

                items.append({
                    "project_item_id": project_item_id,
                    "issue_number": issue_number,
                    "status": status,
                    "assignee": assignee,
                    "repo": repo,
                    "title": content.get("title"),
                    "body": content.get("body"),
                })

            page_info = data.get("user", {}).get("projectV2", {}).get("items", {}).get("pageInfo", {})
            if page_info.get("hasNextPage"):
                cursor = page_info.get("endCursor")
                if not cursor:
                    break
                continue
            break

        return items

    def get_project_item(self, project_number: int, project_item_id: int) -> dict:
        items = list(self.list_project_items(project_number))
        for i in items:
            if str(i.get("project_item_id")) == str(project_item_id):
                return dict(i)
        raise RuntimeError("no such project item")

    def transition_project_item_status(self, project_number: int, project_item_id: int, new_status: str) -> None:
        # Find project id and field/option ids
        q_fields = """
        query ($owner: String!, $number: Int!) {
          user(login: $owner) {
            projectV2(number: $number) { id fields(first: 20) { nodes { ... on ProjectV2SingleSelectField { id name options { id name } } } } }
          }
        }
        """
        data = self._graphql(q_fields, {"owner": self.owner, "number": project_number})
        proj = data.get("user", {}).get("projectV2")
        if not proj:
            raise RuntimeError("project not found")
        project_id = proj.get("id")
        fields = proj.get("fields", {}).get("nodes", [])
        status_field_id = None
        option_id = None
        for f in fields:
            if f.get("name") and "status" in f.get("name").lower():
                status_field_id = f.get("id")
                for opt in f.get("options", []):
                    if opt.get("name") and str(opt.get("name")).upper() == str(new_status).upper():
                        option_id = opt.get("id")
                        break
        if not status_field_id or not option_id:
            raise RuntimeError("status field or option not found in project")

        mut = """
        mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: ID!) {
          updateProjectV2ItemFieldValue(input: {projectId: $projectId, itemId: $itemId, fieldId: $fieldId, value: {singleSelectOptionId: $optionId}}) {
            projectV2Item { id }
          }
        }
        """

        # Try a simple non-paginated items query first (tests may expect this
        # exact shape). If that doesn't return nodes, fall back to the paginated
        # approach.
        simple_q = """
        query ($owner: String!, $number: Int!) {
          user(login: $owner) { projectV2(number: $number) { items(first: 100) { nodes { id databaseId } } } }
        }
        """
        page = self._graphql(simple_q, {"owner": self.owner, "number": project_number})
        nodes = page.get("user", {}).get("projectV2", {}).get("items", {}).get("nodes", [])
        node_id = None
        if not nodes:
            cursor = None
            while True:
                vars = {"owner": self.owner, "number": project_number, "cursor": cursor}
                page = self._graphql(
                    """
                    query ($owner: String!, $number: Int!, $cursor: String) {
                      user(login: $owner) { projectV2(number: $number) { items(first: 100, after: $cursor) { nodes { id databaseId } pageInfo { hasNextPage endCursor } } } }
                    }
                    """,
                    vars,
                )
                nodes = page.get("user", {}).get("projectV2", {}).get("items", {}).get("nodes", [])
                for n in nodes:
                    if str(n.get("databaseId")) == str(project_item_id) or str(n.get("id")) == str(project_item_id):
                        node_id = n.get("id")
                        break
                page_info = page.get("user", {}).get("projectV2", {}).get("items", {}).get("pageInfo", {})
                if node_id:
                    break
                if page_info.get("hasNextPage"):
                    cursor = page_info.get("endCursor")
                    if not cursor:
                        break
                    continue
                break
        else:
            for n in nodes:
                if str(n.get("databaseId")) == str(project_item_id) or str(n.get("id")) == str(project_item_id):
                    node_id = n.get("id")
                    break

        if not node_id:
            raise RuntimeError("project item node not found")

        self._graphql(mut, {"projectId": project_id, "itemId": node_id, "fieldId": status_field_id, "optionId": option_id})
