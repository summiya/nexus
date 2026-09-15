import asyncio

from nexus.logging.context import (
    bind_request_context,
    clear_request_context,
    get_request_context,
)


def test_request_context_is_bound_and_cleared() -> None:
    token = bind_request_context("req_test")
    try:
        context = get_request_context()
        assert context is not None
        assert context.request_id == "req_test"
    finally:
        clear_request_context(token)

    assert get_request_context() is None


def test_concurrent_request_contexts_are_isolated() -> None:
    async def worker(request_id: str) -> str:
        token = bind_request_context(request_id)
        try:
            await asyncio.sleep(0)
            context = get_request_context()
            assert context is not None
            return context.request_id
        finally:
            clear_request_context(token)

    async def run_workers() -> tuple[str, str]:
        first, second = await asyncio.gather(worker("req_a"), worker("req_b"))
        return first, second

    assert asyncio.run(run_workers()) == ("req_a", "req_b")
