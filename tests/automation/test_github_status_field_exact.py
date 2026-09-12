import os

from automation.codex.github import GraphQLGitHubAPI


def test_status_field_exact_match(monkeypatch):
    """Ensure a field named 'Custom Status Metadata' is NOT treated as the
    authoritative Status field (only exact case-insensitive 'Status' should match).
    """
    os.environ["GITHUB_TOKEN"] = "fake-token"
    os.environ["GITHUB_REPOSITORY"] = "owner/repo"
    api = GraphQLGitHubAPI()

    def fake_graphql(query, variables=None):
        # Return a project where the only single-select field contains the
        # word 'Status' but is not named exactly 'Status'. get_project_statuses
        # must raise in this case.
        return {
            "user": {
                "projectV2": {
                    "fields": {
                        "nodes": [
                            {
                                "id": "F-CUSTOM",
                                "name": "Custom Status Metadata",
                                "options": [{"id": "O1", "name": "READY"}],
                            }
                        ]
                    }
                }
            }
        }

    monkeypatch.setattr(api, "_graphql", fake_graphql)
    try:
        api.get_project_statuses(1)
    except RuntimeError as e:
        assert "Status field not found" in str(e)
    else:
        raise AssertionError("get_project_statuses() should have failed without exact 'Status' field")


def test_transition_uses_exact_status_field(monkeypatch):
    """Ensure transition_project_item_status() does not treat
    'Custom Status Metadata' as the authoritative Status field, and that
    it succeeds when a real 'Status' field is present.
    """
    os.environ["GITHUB_TOKEN"] = "fake-token"
    os.environ["GITHUB_REPOSITORY"] = "owner/repo"
    api = GraphQLGitHubAPI()

    calls = []

    def fake_graphql(query, variables=None):
        calls.append((query, variables))
        # q_fields call: project has only a custom-named single-select
        if "fields(first" in query and "ProjectV2SingleSelectField" in query:
            return {
                "user": {
                    "projectV2": {
                        "id": "P1",
                        "fields": {
                            "nodes": [
                                {
                                    "id": "F-CUSTOM",
                                    "name": "Custom Status Metadata",
                                    "options": [{"id": "O1", "name": "READY"}],
                                }
                            ]
                        },
                    }
                }
            }

        # For the items query used later (simple items fetch), return a node
        if "items(first: 100) { nodes { id databaseId } }" in query or "items(first: 100)" in query:
            return {"user": {"projectV2": {"items": {"nodes": [{"id": "N1", "databaseId": 99}]}}}}

        # mutation: if called, return empty success shape
        if "updateProjectV2ItemFieldValue" in query:
            return {"data": {}}

        return {}

    monkeypatch.setattr(api, "_graphql", fake_graphql)

    # Case A: no exact 'Status' field -> should raise
    try:
        api.transition_project_item_status(1, 99, "BUILDING")
    except RuntimeError as e:
        assert "status field or option not found" in str(e)
    else:
        raise AssertionError("transition_project_item_status() should have failed when exact 'Status' field is missing")

    # Case B: add a proper Status field and ensure mutation is invoked
    def fake_graphql_with_status(query, variables=None):
        calls.append((query, variables))
        if "fields(first" in query and "ProjectV2SingleSelectField" in query:
            return {
                "user": {
                    "projectV2": {
                        "id": "P1",
                        "fields": {
                            "nodes": [
                                {
                                    "id": "F-STATUS",
                                    "name": "Status",
                                    "options": [
                                        {"id": "O-BUILDING", "name": "BUILDING"},
                                        {"id": "O-READY", "name": "READY"},
                                    ],
                                }
                            ]
                        },
                    }
                }
            }
        if "items(first: 100) { nodes { id databaseId } }" in query or "items(first: 100)" in query:
            return {"user": {"projectV2": {"items": {"nodes": [{"id": "N1", "databaseId": 99}]}}}}
        if "updateProjectV2ItemFieldValue" in query:
            # indicate mutation was invoked
            return {"data": {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "N1"}}}}
        return {}

    monkeypatch.setattr(api, "_graphql", fake_graphql_with_status)
    # should not raise
    api.transition_project_item_status(1, 99, "BUILDING")
    # ensure a mutation call was made
    assert any("updateProjectV2ItemFieldValue" in q for q, v in calls)
