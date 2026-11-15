import asyncio
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.adapters.db.models import Base
from app.adapters.db.session import create_engine, create_sessionmaker
from app.settings import Settings, get_settings


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    base = get_settings()
    return base.model_copy(update={"postgres_db": f"{base.postgres_db}_test"})


async def _ensure_database(settings: Settings) -> None:
    admin_url = settings.model_copy(update={"postgres_db": "postgres"}).database_url
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :db"), {"db": settings.postgres_db}
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{settings.postgres_db}"'))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def _test_database(test_settings: Settings) -> None:
    try:
        asyncio.run(_ensure_database(test_settings))
    except (OSError, DBAPIError) as e:
        pytest.skip(f"Postgres not reachable: {e}")


@pytest.fixture
async def db_engine(_test_database: None, test_settings: Settings) -> AsyncGenerator[AsyncEngine]:
    engine = create_engine(test_settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def sessionmaker(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(db_engine)
