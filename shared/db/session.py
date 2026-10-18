"""Async database engine and session factory.

Usage:
    async with SessionLocal() as session:
        result = await session.execute(select(User))
"""

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from shared.settings import get_shared_settings


def make_engine(database_url: str | None = None) -> AsyncEngine:
    settings = get_shared_settings()
    url = database_url or settings.DATABASE_URL
    if settings.ENVIRONMENT == "test":
        # Tests run each test in its own event loop, so never reuse pooled connections.
        return create_async_engine(url, poolclass=NullPool)
    return create_async_engine(url, pool_pre_ping=True)


# Creating the engine does not connect yet; the first query does.
engine = make_engine()

# expire_on_commit=False lets you keep using objects after `await session.commit()`.
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
