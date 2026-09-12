from __future__ import annotations

from automation.codex.state import WorkflowState, WorkflowTask


class InMemoryTaskStore:
    """Very small in-memory task registry used by discovery/tests to model existing tasks.

    This is intentionally simple and not a persistent store. It allows tests to
    simulate a previously-created WorkflowTask so claim semantics can be tested
    without introducing external infrastructure.
    """

    def __init__(self) -> None:
        self._store: dict[str, WorkflowTask] = {}

    def get(self, task_id: str) -> WorkflowTask | None:
        return self._store.get(task_id)

    def create_if_missing(self, task_id: str) -> WorkflowTask:
        if task_id not in self._store:
            # New tasks discovered from GitHub start in READY
            self._store[task_id] = WorkflowTask(
                task_id=task_id, state=WorkflowState.READY
            )
        return self._store[task_id]

    def all(self) -> dict[str, WorkflowTask]:
        return dict(self._store)


__all__ = ["InMemoryTaskStore"]
