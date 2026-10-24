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


# --------------------------------------------------------------------------- onboarding helpers


class FakeEmailSender:
    """Keeps sent emails in a list instead of sending them."""

    def __init__(self) -> None:
        self.sent: list = []

    async def send(self, message) -> None:  # type: ignore[no-untyped-def]
        self.sent.append(message)

    def last_code(self) -> str:
        """The 6-digit code from the newest email."""
        import re

        match = re.search(r"\b(\d{6})\b", self.sent[-1].text)
        assert match, "no code in the last email"
        return match.group(1)


@pytest.fixture
def fake_email() -> FakeEmailSender:
    return FakeEmailSender()


@pytest.fixture
def fake_firebase(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """Replaces firebase-admin user changes; returns the list of calls made."""
    from api.core import firebase_users

    calls: list[tuple] = []

    async def update_user(uid, **changes):  # type: ignore[no-untyped-def]
        calls.append(("update_user", uid, changes))

    async def delete_user(uid):  # type: ignore[no-untyped-def]
        calls.append(("delete_user", uid, {}))

    monkeypatch.setattr(firebase_users, "update_user", update_user)
    monkeypatch.setattr(firebase_users, "delete_user", delete_user)
    return calls


def student_claims(**extra) -> dict:  # type: ignore[no-untyped-def]
    """Firebase token claims of the test student (what get_firebase_claims would return)."""
    return {"uid": STUDENT.firebase_uid, "email": STUDENT.email, "email_verified": False, **extra}


def make_api_client(  # type: ignore[no-untyped-def]
    *, user=None, claims=None, ai=None, email=None
) -> AsyncClient:
    """API client with any of: logged-in user, Firebase claims, fake AI client, fake email."""
    from api.core.ai_client import get_ai_client
    from api.core.email import get_email_sender
    from api.core.security import get_firebase_claims

    app = create_api_app()
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    if claims is not None:
        app.dependency_overrides[get_firebase_claims] = lambda: claims
    if ai is not None:
        app.dependency_overrides[get_ai_client] = lambda: ai
    if email is not None:
        app.dependency_overrides[get_email_sender] = lambda: email
    return _client(app)


async def delete_test_user(session: AsyncSession) -> None:
    """Remove the test student and everything they own (cascades), plus their papers/codes."""
    from sqlalchemy import delete, or_, select

    from shared.db.models import EmailCode, Paper, User

    # register creates the student with a new id, so match by uid / email too
    is_student = or_(
        User.id == STUDENT.id,
        User.firebase_uid == STUDENT.firebase_uid,
        User.email == STUDENT.email,
    )
    user_ids = list((await session.execute(select(User.id).where(is_student))).scalars())
    if user_ids:
        await session.execute(delete(Paper).where(Paper.created_by.in_(user_ids)))
        await session.execute(delete(User).where(User.id.in_(user_ids)))
    await session.execute(delete(EmailCode).where(EmailCode.email.like("%@test.local")))
    await session.commit()


@pytest.fixture
async def student_in_db(db_session: AsyncSession) -> AsyncIterator[uuid.UUID]:
    """The test student as a real (registered, not yet verified) users row."""
    from shared.db.models import User

    await delete_test_user(db_session)
    db_session.add(
        User(
            id=STUDENT.id,
            firebase_uid=STUDENT.firebase_uid,
            email=STUDENT.email,
            display_name="Nethmi Perera",
            role=UserRole.STUDENT,
        )
    )
    await db_session.commit()
    yield STUDENT.id
    await delete_test_user(db_session)
