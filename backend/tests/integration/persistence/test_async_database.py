import asyncio

from alembic.config import Config
from sqlalchemy import Engine, text

from nexus.infrastructure.persistence.session import build_database


def test_async_session_executes_against_postgresql(
    migrated_database: tuple[Config, Engine],
) -> None:
    _, migrated_engine = migrated_database
    database = build_database(migrated_engine.url.render_as_string(hide_password=False))

    async def execute_query() -> None:
        try:
            async with database.session_factory() as session:
                assert await session.scalar(text("SELECT 1")) == 1
        finally:
            await database.dispose()

    asyncio.run(execute_query())
