"""Migrations: upgrade -> downgrade -> upgrade on an empty database, and no model drift."""

import asyncio

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import create_async_engine

import shared.db.models  # noqa: F401  (registers every table)
from shared.db.base import Base
from tests.db.conftest import alembic

pytestmark = pytest.mark.db


def schema_differences(database_url: str) -> list:
    """What `alembic revision --autogenerate` would still want to change."""

    async def compare() -> list:
        engine = create_async_engine(database_url)
        try:
            async with engine.connect() as conn:

                def run(sync_conn):  # type: ignore[no-untyped-def]
                    context = MigrationContext.configure(sync_conn, opts={"compare_type": True})
                    return compare_metadata(context, Base.metadata)

                return await conn.run_sync(run)
        finally:
            await engine.dispose()

    return asyncio.run(compare())


def test_upgrade_downgrade_upgrade(scratch_db):
    alembic("upgrade head", scratch_db)
    alembic("downgrade base", scratch_db)
    alembic("upgrade head", scratch_db)


def test_models_match_the_migrated_database(scratch_db):
    """Models and migrations agree. (CHECK constraints are not compared by Alembic;
    tests/db/test_constraints.py checks the important ones directly.)"""
    alembic("upgrade head", scratch_db)
    assert schema_differences(scratch_db) == []
