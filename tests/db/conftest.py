"""Fixtures for the database (schema) tests.

* `session`     - a session on the normal test database; everything is ROLLED BACK at the end,
                  so these tests never leave rows behind.
* `scratch_db`  - the URL of a brand-new, empty database next to the test database
                  (created for the test, dropped afterwards). Used to run migrations and
                  the seed without touching the normal test database.
"""

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.session import SessionLocal
from shared.settings import get_shared_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
EMBEDDING_DIM = 768


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as s:
        yield s
        await s.rollback()


def _plain_dsn(url: str, database: str) -> str:
    """postgresql+asyncpg://u:p@h/db -> postgresql://u:p@h/<database> (for asyncpg)."""
    parsed = make_url(url).set(drivername="postgresql", database=database)
    return parsed.render_as_string(hide_password=False)


def run_script(args: list[str], database_url: str) -> subprocess.CompletedProcess[str]:
    """Run `python <args>` from the repo root with DATABASE_URL pointing at `database_url`."""
    env = {**os.environ, "DATABASE_URL": database_url}
    return subprocess.run(
        [sys.executable, *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def alembic(command: str, database_url: str) -> None:
    result = run_script(["-m", "alembic", *command.split()], database_url)
    assert result.returncode == 0, f"alembic {command} failed:\n{result.stderr[-3000:]}"


@pytest.fixture
def scratch_db() -> Iterator[str]:
    """Create an empty database, give its SQLAlchemy URL, drop it afterwards."""
    base_url = get_shared_settings().DATABASE_URL
    name = f"brainbox_scratch_{uuid.uuid4().hex[:8]}"
    admin_dsn = _plain_dsn(base_url, "postgres")

    async def admin(sql: str) -> None:
        conn = await asyncpg.connect(admin_dsn)
        try:
            await conn.execute(sql)
        finally:
            await conn.close()

    try:
        asyncio.run(admin(f'CREATE DATABASE "{name}"'))
    except Exception as exc:  # e.g. the database user may not create databases
        pytest.skip(f"cannot create a scratch database ({type(exc).__name__}: {exc})")
    try:
        yield make_url(base_url).set(database=name).render_as_string(hide_password=False)
    finally:
        asyncio.run(admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def vector(*values: float) -> list[float]:
    """A small fake embedding padded with zeros to 768 numbers."""
    return list(values) + [0.0] * (EMBEDDING_DIM - len(values))
