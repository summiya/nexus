import os

from automation.codex.github import GraphQLGitHubAPI


def test_graphql_queries_use_user_owner(monkeypatch):
    os.environ["GITHUB_TOKEN"] = "fake-token"
    os.environ["GITHUB_REPOSITORY"] = "summiya/nexus"
    api = GraphQLGitHubAPI()

    recorded = {}

    def fake_graphql(query, variables=None):
        recorded["query"] = query
        recorded["variables"] = variables
        # return minimal shape that get_project_statuses handles
        return {"user": {"projectV2": None}}

    monkeypatch.setattr(api, "_graphql", fake_graphql)
    api.get_project_statuses(1)
    assert "user(" in recorded["query"]
    assert "repository(" not in recorded["query"]


def test_transition_mutation_invoked(monkeypatch):
    os.environ["GITHUB_TOKEN"] = "fake-token"
    os.environ["GITHUB_REPOSITORY"] = "summiya/nexus"
    api = GraphQLGitHubAPI()

    calls = []

    def fake_graphql(query, variables=None):
        calls.append((query, variables))
        # emulate responses:
        if "fields(first" in query:
            return {"user": {"projectV2": {"id": "P1", "fields": {"nodes": [{"id": "F1", "name": "Status", "options": [{"id": "O1", "name": "BUILDING"}, {"id": "O2", "name": "READY"}] }]}}}}
        if "items(first: 100) { nodes { id databaseId } }" in query:
            return {"user": {"projectV2": {"items": {"nodes": [{"id": "N1", "databaseId": 99}]}}}}
        # mutation call returns empty data
        return {}

    monkeypatch.setattr(api, "_graphql", fake_graphql)
    # should not raise
    api.transition_project_item_status(1, 99, "BUILDING")
    # ensure mutation was called (last call)
    assert any("updateProjectV2ItemFieldValue" in q for q, v in calls)
