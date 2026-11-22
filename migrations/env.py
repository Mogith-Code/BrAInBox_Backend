"""Alembic environment (async). Owner: Keshomigha.

Reads DATABASE_URL from shared settings and compares against every model imported
in `shared/db/models/__init__.py`.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import shared.db.models  # noqa: F401  (registers every table on Base.metadata)
from shared.db.base import Base
from shared.settings import get_shared_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
DATABASE_URL = get_shared_settings().DATABASE_URL


def run_migrations_offline() -> None:
    """Print the SQL instead of running it:  alembic upgrade head --sql"""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# Any fixed number: the id of the PostgreSQL advisory lock held while migrating.
MIGRATION_LOCK_ID = 727_001


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        # Two containers starting at once (each runs `alembic upgrade head`) would otherwise
        # migrate together. The second one waits here, then finds nothing left to do. The lock
        # is released when this transaction ends.
        connection.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": MIGRATION_LOCK_ID})
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(DATABASE_URL)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
