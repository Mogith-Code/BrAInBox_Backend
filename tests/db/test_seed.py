"""The dev seed is idempotent: running it twice leaves the same row counts."""

import asyncio

import asyncpg
import pytest
from sqlalchemy.engine import make_url

from tests.db.conftest import alembic, run_script

pytestmark = pytest.mark.db

TABLES = [
    "units",
    "topics",
    "concepts",
    "community_groups",
    "app_config",
    "questions",
    "mcq_options",
]


def row_counts(database_url: str) -> dict[str, int]:
    dsn = make_url(database_url).set(drivername="postgresql").render_as_string(hide_password=False)

    async def count() -> dict[str, int]:
        conn = await asyncpg.connect(dsn)
        try:
            return {t: await conn.fetchval(f"SELECT count(*) FROM {t}") for t in TABLES}
        finally:
            await conn.close()

    return asyncio.run(count())


def seed(database_url: str) -> None:
    result = run_script(["-m", "scripts.seed_dev", "--with-samples"], database_url)
    assert result.returncode == 0, result.stderr[-3000:]


def test_seed_twice_changes_nothing(scratch_db):
    alembic("upgrade head", scratch_db)
    seed(scratch_db)
    first = row_counts(scratch_db)
    seed(scratch_db)
    assert row_counts(scratch_db) == first

    assert first["units"] == 10
    assert first["community_groups"] == 11  # General + one per unit
    assert first["app_config"] == 2  # AL_EXAM_DATES, DAILY_LIMITS
    assert first["questions"] == 15
    assert first["mcq_options"] == 75  # 5 options each
