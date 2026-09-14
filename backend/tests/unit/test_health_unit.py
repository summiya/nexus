import asyncio

from nexus.api.health import health


def test_health_returns_status_ok() -> None:
    result = asyncio.run(health())

    assert result == {"status": "ok"}
