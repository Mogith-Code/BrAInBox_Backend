"""Shared test fixtures.

* No Firebase: `get_current_user` is overridden with fake users (student / admin).
* No AI keys: the deterministic fake providers are always used.
* Database: tests marked `@pytest.mark.db` need PostgreSQL + pgvector with migrations applied
  (`alembic upgrade head`). They are skipped automatically when no database is reachable.
  Point them at a database with TEST_DATABASE_URL (or DATABASE_URL).
"""

import os

# Settings are read at import time, so set the test environment BEFORE importing the apps.
os.environ["ENVIRONMENT"] = "test"
os.environ["USE_FAKE_AI"] = "true"
os.environ["AI_SERVICE_TOKEN"] = "test-service-token"
os.environ["GEMINI_API_KEY"] = ""
if os.environ.get("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]

import asyncio  # noqa: E402
import uuid  # noqa: E402
from collections.abc import AsyncIterator  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from ai_service.main import create_app as create_ai_app  # noqa: E402
from ai_service.providers import reset_providers  # noqa: E402
from api.core.security import CurrentUser, get_current_user  # noqa: E402
from api.main import create_app as create_api_app  # noqa: E402
from shared.db.session import SessionLocal, make_engine  # noqa: E402
from shared.enums import UserRole  # noqa: E402

SERVICE_TOKEN = "test-service-token"

STUDENT = CurrentUser(
    id=uuid.UUID(int=1),
    firebase_uid="test-student",
    email="student@test.local",
    role=UserRole.STUDENT,
)
ADMIN = CurrentUser(
    id=uuid.UUID(int=2), firebase_uid="test-admin", email="admin@test.local", role=UserRole.ADMIN
)


# --------------------------------------------------------------------------- database check


def _database_status() -> str | None:
    """None if the test database is usable, otherwise the reason to skip."""

    async def check() -> str | None:
        engine = make_engine()
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
                migrated = await conn.execute(
                    text("SELECT to_regclass('public.document_chunks') IS NOT NULL")
                )
                if not migrated.scalar():
                    return "database has no tables - run `alembic upgrade head`"
            return None
        except Exception as exc:
            return f"no database reachable ({type(exc).__name__})"
        finally:
            await engine.dispose()

    try:
        return asyncio.run(asyncio.wait_for(check(), timeout=5))
    except Exception as exc:
        return f"no database reachable ({type(exc).__name__})"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if not any(item.get_closest_marker("db") for item in items):
        return
    reason = _database_status()
    if reason:
        skip = pytest.mark.skip(reason=reason)
        for item in items:
            if item.get_closest_marker("db"):
                item.add_marker(skip)


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def fake_ai_providers() -> None:
    """Start every test with fresh fake providers."""
    reset_providers()


def _client(app) -> AsyncClient:  # type: ignore[no-untyped-def]
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def anon_client() -> AsyncIterator[AsyncClient]:
    """API client with no logged-in user (no token)."""
    async with _client(create_api_app()) as c:
        yield c


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """API client logged in as a student."""
    app = create_api_app()
    app.dependency_overrides[get_current_user] = lambda: STUDENT
    async with _client(app) as c:
        yield c


@pytest.fixture
async def admin_client() -> AsyncIterator[AsyncClient]:
    """API client logged in as an admin."""
    app = create_api_app()
    app.dependency_overrides[get_current_user] = lambda: ADMIN
    async with _client(app) as c:
        yield c


@pytest.fixture
async def ai_client() -> AsyncIterator[AsyncClient]:
    """Client for the internal AI service, sending the service token."""
    async with _client(create_ai_app()) as c:
        c.headers["X-Service-Token"] = SERVICE_TOKEN
        yield c


@pytest.fixture
async def ai_anon_client() -> AsyncIterator[AsyncClient]:
    """Client for the AI service WITHOUT the service token."""
    async with _client(create_ai_app()) as c:
        yield c


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """A real database session (only for tests marked @pytest.mark.db)."""
    async with SessionLocal() as session:
        yield session
