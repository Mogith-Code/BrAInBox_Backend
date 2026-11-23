"""Learn tab endpoints (/api/v1/learn) against a real database + the real ai_service (mock LLM).

Needs PostgreSQL (TEST_DATABASE_URL). The tests run in their OWN scratch database (created next to
the test database, migrated with `alembic upgrade head`, seeded with scripts/seed_learn.py, and
dropped at the end), because other tests need the normal test database to stay empty.
This also checks that the migrations run on a clean database and that the seed is idempotent.
"""

import asyncio
import functools
import importlib
import io
import sys
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from ai_service.config import get_settings as get_ai_settings
from ai_service.main import create_app as create_ai_app
from ai_service.pipelines.summarization import learn_upload
from api.core.ai_client import AIClient, get_ai_client
from api.core.config import get_settings as get_api_settings
from api.core.database import get_session
from api.core.security import CurrentUser, get_current_user
from api.main import create_app as create_api_app
from api.modules.learn import service as learn_service
from shared.db.models import (
    AIJob,
    Attempt,
    Note,
    Paper,
    Question,
    Response,
    Topic,
    TopicBookmark,
    Upload,
    User,
    UserTopicProgress,
)
from shared.enums import QuestionType, UserRole
from shared.settings import get_shared_settings
from tests.conftest import SERVICE_TOKEN, STUDENT, _client
from tests.samples import OSMOSIS_NOTES, make_pdf

pytestmark = pytest.mark.db

L = "/api/v1/learn"
OTHER = CurrentUser(
    id=uuid.UUID(int=3), firebase_uid="test-other", email="other@test.local", role=UserRole.STUDENT
)
UNIT6_TOPICS = [
    "Mendelian inheritance",
    "Monohybrid & dihybrid crosses",
    "Test cross & back cross",
    "Incomplete dominance & codominance",
    "Multiple alleles & blood groups",
    "Sex linkage",
    "Pedigree analysis",
    "Chromosomal mutations",
    "Polygenic inheritance",
]
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ORIGINAL_ASYNC_CLIENT = httpx.AsyncClient
QUESTION_STEM = "learn-test question"


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="session")
def learn_db(tmp_path_factory):  # type: ignore[no-untyped-def]
    """A scratch database: migrated from zero, seeded twice. Yields its session factory."""
    import asyncpg
    from sqlalchemy.engine import make_url

    from tests.db.conftest import _plain_dsn, alembic

    base_url = get_shared_settings().DATABASE_URL
    name = f"brainbox_learn_{uuid.uuid4().hex[:8]}"
    admin_dsn = _plain_dsn(base_url, "postgres")

    async def admin(sql: str) -> None:
        conn = await asyncpg.connect(admin_dsn, timeout=5)
        try:
            await conn.execute(sql)
        finally:
            await conn.close()

    try:
        asyncio.run(admin(f'CREATE DATABASE "{name}"'))
    except Exception as exc:
        pytest.skip(f"cannot create a scratch database ({type(exc).__name__})")
    url = make_url(base_url).set(database=name).render_as_string(hide_password=False)
    # The seed copies the sample diagram to local storage: keep it out of the repo folder.
    api_settings = get_api_settings()
    old_storage = api_settings.LOCAL_STORAGE_DIR
    api_settings.LOCAL_STORAGE_DIR = str(tmp_path_factory.mktemp("learn_storage"))
    try:
        alembic("upgrade head", url)
        engine = create_async_engine(url, poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        if "scripts" not in sys.path:
            sys.path.insert(0, "scripts")
        seed_learn = importlib.import_module("seed_learn")
        first = asyncio.run(seed_learn.seed(factory))
        second = asyncio.run(seed_learn.seed(factory))  # idempotent: nothing duplicated
        assert first == second
        assert (first.subjects, first.units, first.topics) == (3, 10, 98)
        assert (first.notes, first.diagrams, first.videos) == (2, 1, 2)
        yield factory
        asyncio.run(engine.dispose())
    finally:
        api_settings.LOCAL_STORAGE_DIR = old_storage
        asyncio.run(admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture
async def db_session(learn_db):  # type: ignore[no-untyped-def]
    """Session on the Learn scratch database (overrides the conftest one)."""
    async with learn_db() as session:
        yield session


async def _cleanup(session) -> None:  # type: ignore[no-untyped-def]
    ids = [STUDENT.id, OTHER.id]
    await session.execute(delete(Question).where(Question.stem == QUESTION_STEM))
    await session.execute(delete(Paper).where(Paper.created_by.in_(ids)))
    await session.execute(delete(AIJob).where(AIJob.requested_by.in_(ids)))
    await session.execute(delete(User).where(User.id.in_(ids)))  # cascades the rest
    await session.commit()


@pytest.fixture
async def users(db_session):  # type: ignore[no-untyped-def]
    await _cleanup(db_session)
    for u in (STUDENT, OTHER):
        db_session.add(User(id=u.id, firebase_uid=u.firebase_uid, email=u.email, role=u.role))
    await db_session.commit()
    yield
    await db_session.rollback()
    await _cleanup(db_session)


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    for settings in (get_api_settings(), get_ai_settings()):
        monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def ai(monkeypatch) -> AIClient:  # type: ignore[no-untyped-def]
    """AIClient that talks to the real ai_service app in memory (fake providers, mock LLM)."""
    transport = httpx.ASGITransport(app=create_ai_app())
    monkeypatch.setattr(
        httpx, "AsyncClient", functools.partial(ORIGINAL_ASYNC_CLIENT, transport=transport)
    )
    return AIClient("http://ai-service", SERVICE_TOKEN)


def learn_client(user, ai, factory, monkeypatch):  # type: ignore[no-untyped-def]
    """API client on the scratch database (requests AND background jobs)."""

    async def scratch_session():  # type: ignore[no-untyped-def]
        async with factory() as session:
            yield session

    monkeypatch.setattr(learn_service, "SessionLocal", factory)  # background jobs
    app = create_api_app()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_ai_client] = lambda: ai
    app.dependency_overrides[get_session] = scratch_session
    return _client(app)


@pytest.fixture
async def me(users, ai, upload_dir, learn_db, monkeypatch):  # type: ignore[no-untyped-def]
    async with learn_client(STUDENT, ai, learn_db, monkeypatch) as c:
        yield c


@pytest.fixture
async def other(users, ai, upload_dir, learn_db, monkeypatch):  # type: ignore[no-untyped-def]
    async with learn_client(OTHER, ai, learn_db, monkeypatch) as c:
        yield c


async def topic_id(session, code: str = "bio-6.1") -> uuid.UUID:  # type: ignore[no-untyped-def]
    return (await session.execute(select(Topic.id).where(Topic.code == code))).scalar_one()


def assert_error(response, status: int, code: str) -> None:  # type: ignore[no-untyped-def]
    assert response.status_code == status, response.text
    body = response.json()
    assert body["code"] == code and body["error"]["code"] == code
    assert body["detail"] == body["error"]["message"]


# --------------------------------------------------------------------------- auth + docs


async def test_every_route_needs_login(anon_client):
    for method, path in [
        ("GET", "/subjects"),
        ("GET", "/topics/bio-6.1"),
        ("POST", "/bookmarks/bio-6.1"),
        ("GET", "/uploads"),
    ]:
        response = await anon_client.request(method, L + path)
        assert_error(response, 401, "UNAUTHORIZED")


async def test_docs_list_every_learn_route(anon_client):
    paths = (await anon_client.get("/openapi.json")).json()["paths"]
    learn = {p for p in paths if p.startswith(L)}
    assert len(learn) == 20
    assert f"{L}/uploads/{{upload_id}}/save-to-short-notes" in learn


async def test_cors_allows_the_flutter_dev_origin(anon_client):
    response = await anon_client.options(
        f"{L}/subjects",
        headers={"Origin": "http://localhost:53172", "Access-Control-Request-Method": "GET"},
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:53172"


# --------------------------------------------------------------------------- syllabus tree


async def test_subjects(me):
    body = (await me.get(f"{L}/subjects")).json()
    by_code = {s["code"]: s for s in body["items"]}
    assert body["total"] == len(body["items"])
    assert by_code["biology"]["available"] is True
    assert by_code["biology"]["syllabus_version"] == "2025"
    assert by_code["biology"]["unit_count"] == 10
    assert by_code["chemistry"]["available"] is False and by_code["physics"]["available"] is False


async def test_units_of_a_subject(me):
    body = (await me.get(f"{L}/subjects/biology/units")).json()
    assert body["total"] == 10
    counts = [u["topic_count"] for u in body["items"]]
    assert counts == [4, 14, 11, 12, 18, 9, 9, 8, 7, 6]
    unit6 = body["items"][5]
    assert unit6 | {"id": None} == {
        "id": None,
        "code": "u6",
        "number": 6,
        "title": "Genetics",
        "icon_key": "dna",
        "order": 6,
        "topic_count": 9,
        "mastery_percent": 0,
        "mastery_level": "weak",
    }


async def test_units_filter(me):
    body = (await me.get(f"{L}/subjects/biology/units", params={"q": "MENDEL"})).json()
    assert [u["number"] for u in body["items"]] == [6]  # matched by a topic title
    body = (await me.get(f"{L}/subjects/biology/units", params={"q": "microbio"})).json()
    assert [u["number"] for u in body["items"]] == [9]


async def test_units_unknown_subject(me):
    assert_error(await me.get(f"{L}/subjects/nope/units"), 404, "SUBJECT_NOT_FOUND")


async def test_unit_detail(me, db_session):
    body = (await me.get(f"{L}/units/u6")).json()
    assert [t["title"] for t in body["topics"]] == UNIT6_TOPICS
    assert [t["number"] for t in body["topics"]] == [f"6.{n}" for n in range(1, 10)]
    assert body["subject"]["code"] == "biology"
    assert (body["mastered_count"], body["weak_count"], body["mastery_percent"]) == (0, 0, 0)
    first = body["topics"][0]
    assert (first["status"], first["progress_percent"], first["is_weak"]) == (
        "not_started",
        0,
        False,
    )
    by_uuid = (await me.get(f"{L}/units/{body['id']}")).json()
    assert by_uuid["id"] == body["id"]


async def test_unit_not_found(me):
    assert_error(await me.get(f"{L}/units/u99"), 404, "UNIT_NOT_FOUND")
    assert_error(await me.get(f"{L}/units/{uuid.uuid4()}"), 404, "UNIT_NOT_FOUND")


async def test_topic_detail(me):
    body = (await me.get(f"{L}/topics/bio-6.1")).json()
    assert body["title"] == "Mendelian inheritance" and body["number"] == "6.1"
    assert body["breadcrumb"]["subject"]["name"] == "Biology"
    assert body["breadcrumb"]["unit"] | {"id": None} == {
        "id": None,
        "code": "u6",
        "number": 6,
        "title": "Genetics",
    }
    assert body["mastery"] == {"mastery_percent": 0, "mastery_level": "weak", "is_weak": False}
    assert body["is_bookmarked"] is False
    assert (body["syllabus_version"], body["is_outdated"]) == ("2025", False)
    assert (body["has_full_notes"], body["has_short_notes"]) == (True, True)
    other_topic = (await me.get(f"{L}/topics/bio-6.2")).json()
    assert (other_topic["has_full_notes"], other_topic["has_short_notes"]) == (False, False)


async def test_topic_not_found(me):
    assert_error(await me.get(f"{L}/topics/bio-99.9"), 404, "TOPIC_NOT_FOUND")


# --------------------------------------------------------------------------- notes


async def test_official_notes(me):
    full = (await me.get(f"{L}/topics/bio-6.1/notes", params={"type": "full"})).json()
    types = {b["type"] for b in full["blocks"]}
    assert types == {"heading", "paragraph", "definition", "tip", "bullet_list", "table", "image"}
    assert (full["is_own"], full["ai_generated"], full["source"]) == (False, False, "manual")
    texts = " ".join(b.get("text", "") for b in full["blocks"])
    assert "law of segregation" in texts.lower() and "Genotype" in texts
    assert any("2021 Paper II" in b["text"] for b in full["blocks"] if b["type"] == "tip")
    assert any("9" in r[-1] for b in full["blocks"] if b["type"] == "table" for r in b["rows"])
    short = (await me.get(f"{L}/topics/bio-6.1/notes", params={"type": "short"})).json()
    assert short["type"] == "short"
    default = (await me.get(f"{L}/topics/bio-6.1/notes")).json()
    assert default["type"] == "full"


async def test_notes_not_found_and_bad_type(me):
    assert_error(await me.get(f"{L}/topics/bio-6.2/notes"), 404, "NOTES_NOT_FOUND")
    assert_error(await me.get(f"{L}/topics/nope/notes"), 404, "TOPIC_NOT_FOUND")
    assert_error(
        await me.get(f"{L}/topics/bio-6.1/notes", params={"type": "long"}), 422, "VALIDATION_ERROR"
    )


async def _generate(client, topic="bio-6.2", **body):  # type: ignore[no-untyped-def]
    response = await client.post(f"{L}/topics/{topic}/notes/generate", json=body)
    assert response.status_code == 202, response.text
    return response.json()


async def test_generate_notes_with_the_mock_llm(me, other):
    accepted = await _generate(me, type="full", depth="quick")
    assert accepted["status"] == "queued"
    job = (await me.get(f"{L}/jobs/{accepted['job_id']}")).json()  # background task ran
    assert (job["status"], job["kind"], job["cached"], job["error"]) == (
        "done",
        "notes",
        False,
        None,
    )
    assert job["started_at"] and job["finished_at"]

    note = (await me.get(f"{L}/topics/bio-6.2/notes")).json()
    assert note["id"] == job["result_id"]
    assert (note["is_own"], note["ai_generated"], note["source"], note["depth"]) == (
        True,
        True,
        "ai",
        "quick",
    )
    assert note["blocks"][0]["type"] == "heading" and note["read_minutes"] >= 1
    topic = (await me.get(f"{L}/topics/bio-6.2")).json()
    assert topic["has_full_notes"] is True

    # Another student cannot see my job or my note.
    assert_error(await other.get(f"{L}/jobs/{accepted['job_id']}"), 404, "JOB_NOT_FOUND")
    assert_error(await other.get(f"{L}/topics/bio-6.2/notes"), 404, "NOTES_NOT_FOUND")


async def test_my_note_is_shown_before_the_official_one(me, other):
    await _generate(me, topic="bio-6.1", type="short")
    mine = (await me.get(f"{L}/topics/bio-6.1/notes", params={"type": "short"})).json()
    theirs = (await other.get(f"{L}/topics/bio-6.1/notes", params={"type": "short"})).json()
    assert mine["is_own"] is True and theirs["is_own"] is False
    bullets = [i for b in mine["blocks"] if b["type"] == "bullet_list" for i in b["items"]]
    assert 8 <= len(bullets) <= 15


async def test_same_request_within_24h_is_cached(me, db_session):
    first = await _generate(me, type="full", depth="standard", include_examples=False)
    first_job = (await me.get(f"{L}/jobs/{first['job_id']}")).json()
    again = await _generate(me, type="full", depth="standard", include_examples=False)
    assert again["status"] == "done"  # no AI call
    job = (await me.get(f"{L}/jobs/{again['job_id']}")).json()
    assert job["cached"] is True and job["result_id"] == first_job["result_id"]

    different = await _generate(me, type="full", depth="detailed")
    job = (await me.get(f"{L}/jobs/{different['job_id']}")).json()
    assert job["cached"] is False and job["result_id"] != first_job["result_id"]

    # Older than 24 h -> generated again.
    note = await db_session.get(Note, uuid.UUID(first_job["result_id"]))
    note.created_at = datetime.now(UTC) - timedelta(hours=25)
    await db_session.commit()
    later = await _generate(me, type="full", depth="standard", include_examples=False)
    assert later["status"] == "queued"


async def test_failed_generation_is_reported(me, monkeypatch):
    from ai_service.providers import set_providers

    class BrokenLLM:
        name = "broken"

        async def complete(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            return "not json"

    set_providers(llm_client=BrokenLLM())
    accepted = await _generate(me, type="full")
    job = (await me.get(f"{L}/jobs/{accepted['job_id']}")).json()
    assert (job["status"], job["error_code"], job["result_id"]) == (
        "failed",
        "INVALID_AI_OUTPUT",
        None,
    )
    assert "invalid notes twice" in job["error"]


async def test_generate_validation_and_404(me):
    response = await me.post(f"{L}/topics/bio-6.2/notes/generate", json={"depth": "huge"})
    assert_error(response, 422, "VALIDATION_ERROR")
    response = await me.post(f"{L}/topics/nope/notes/generate", json={})
    assert_error(response, 404, "TOPIC_NOT_FOUND")
    assert_error(await me.get(f"{L}/jobs/{uuid.uuid4()}"), 404, "JOB_NOT_FOUND")


# --------------------------------------------------------------------------- diagrams / videos


async def test_diagrams(me):
    body = (await me.get(f"{L}/topics/bio-6.1/diagrams")).json()
    assert body["total"] == 1
    diagram = body["items"][0]
    assert diagram["image_url"].endswith("seed-dihybrid-punnett.png")
    assert diagram["ai_generated"] is False and "9:3:3:1" in diagram["caption"]
    assert (await me.get(f"{L}/topics/bio-6.2/diagrams")).json() == {"items": [], "total": 0}
    assert_error(await me.get(f"{L}/topics/nope/diagrams"), 404, "TOPIC_NOT_FOUND")


async def test_videos(me):
    body = (await me.get(f"{L}/topics/bio-6.1/videos")).json()
    assert body["total"] == 2
    assert [v["order"] for v in body["items"]] == [1, 2]
    assert body["items"][0]["duration_seconds"] == 540
    assert_error(await me.get(f"{L}/topics/nope/videos"), 404, "TOPIC_NOT_FOUND")


# --------------------------------------------------------------------------- practice + mastery


async def add_practice(session, user_id, topic_code: str, results: list[bool]) -> None:  # type: ignore[no-untyped-def]
    tid = await topic_id(session, topic_code)
    paper = Paper(title="learn-test", created_by=user_id)
    session.add(paper)
    await session.flush()
    attempt = Attempt(paper_id=paper.id, user_id=user_id, status="graded", topic_id=tid)
    session.add(attempt)
    await session.flush()
    start = datetime.now(UTC) - timedelta(hours=1)
    for n, correct in enumerate(results):
        question = Question(
            topic_id=tid, question_type=QuestionType.MCQ, stem=QUESTION_STEM, created_by=user_id
        )
        session.add(question)
        await session.flush()
        session.add(
            Response(
                attempt_id=attempt.id,
                question_id=question.id,
                is_correct=correct,
                answered_at=start + timedelta(minutes=n),
            )
        )
    await session.commit()


async def test_practice_summary_without_practice(me):
    body = (await me.get(f"{L}/topics/bio-6.1/practice-summary")).json()
    assert body == {"question_count": 0, "accuracy_percent": 0, "last_attempt_at": None}
    assert_error(await me.get(f"{L}/topics/nope/practice-summary"), 404, "TOPIC_NOT_FOUND")


async def test_practice_drives_mastery(me, other, db_session):
    await add_practice(db_session, STUDENT.id, "bio-6.3", [True, False, False, False])
    body = (await me.get(f"{L}/topics/bio-6.3/practice-summary")).json()
    assert (body["question_count"], body["accuracy_percent"]) == (4, 25)
    assert body["last_attempt_at"] is not None
    topic = (await me.get(f"{L}/topics/bio-6.3")).json()
    assert topic["mastery"] == {"mastery_percent": 25, "mastery_level": "weak", "is_weak": True}
    assert topic["status"] == "in_progress"

    # 20/20 on another topic of the unit -> mastered (>= 90 % with >= 10 answers).
    await add_practice(db_session, STUDENT.id, "bio-6.4", [True] * 20)
    unit = (await me.get(f"{L}/units/u6")).json()
    t64 = next(t for t in unit["topics"] if t["number"] == "6.4")
    assert (t64["status"], t64["mastery_level"], t64["mastery_percent"]) == (
        "mastered",
        "mastered",
        100,
    )
    assert (unit["mastered_count"], unit["weak_count"]) == (1, 1)
    assert unit["mastery_percent"] == round((25 + 100) / 9)

    # The other student's numbers are untouched.
    theirs = (await other.get(f"{L}/topics/bio-6.3/practice-summary")).json()
    assert theirs["question_count"] == 0


# --------------------------------------------------------------------------- progress


async def test_progress_events(me, other, db_session):
    opened = await me.post(f"{L}/topics/bio-6.5/progress", json={"event": "opened"})
    assert opened.status_code == 200, opened.text
    body = opened.json()
    assert (body["status"], body["progress_percent"], body["seconds_spent"]) == (
        "in_progress",
        0,
        0,
    )
    assert body["last_opened_at"] is not None

    await me.post(f"{L}/topics/bio-6.5/progress", json={"event": "read", "seconds": 90})
    body = (
        await me.post(
            f"{L}/topics/bio-6.5/progress",
            json={"event": "read", "seconds": 30, "progress_percent": 40},
        )
    ).json()
    assert (body["seconds_spent"], body["progress_percent"]) == (120, 40)
    # progress never goes down
    body = (
        await me.post(
            f"{L}/topics/bio-6.5/progress", json={"event": "read", "progress_percent": 10}
        )
    ).json()
    assert body["progress_percent"] == 40
    body = (
        await me.post(f"{L}/topics/bio-6.5/progress", json={"event": "read", "completed": True})
    ).json()
    assert body["progress_percent"] == 100
    assert body["mastery"]["mastery_percent"] == 50  # reading only counts half

    topic = (await me.get(f"{L}/topics/bio-6.5")).json()
    assert (topic["status"], topic["progress_percent"], topic["seconds_spent"]) == (
        "in_progress",
        100,
        120,
    )
    assert (await other.get(f"{L}/topics/bio-6.5")).json()["status"] == "not_started"
    rows = await db_session.execute(
        select(UserTopicProgress).where(UserTopicProgress.user_id == STUDENT.id)
    )
    assert len(rows.scalars().all()) == 1  # one row, upserted


async def test_progress_validation(me):
    response = await me.post(f"{L}/topics/bio-6.5/progress", json={"event": "skipped"})
    assert_error(response, 422, "VALIDATION_ERROR")
    response = await me.post(f"{L}/topics/bio-6.5/progress", json={"event": "read", "seconds": -1})
    assert_error(response, 422, "VALIDATION_ERROR")
    response = await me.post(f"{L}/topics/nope/progress", json={"event": "opened"})
    assert_error(response, 404, "TOPIC_NOT_FOUND")


# --------------------------------------------------------------------------- bookmarks + search


async def test_bookmarks(me, other, db_session):
    for _ in range(2):  # idempotent
        response = await me.post(f"{L}/bookmarks/bio-6.1")
        assert response.status_code == 200
        assert response.json()["is_bookmarked"] is True
    await me.post(f"{L}/bookmarks/bio-2.4")

    body = (await me.get(f"{L}/bookmarks")).json()
    assert body["total"] == 2
    assert body["items"][0]["topic"]["code"] == "bio-2.4"  # newest first
    assert body["items"][1]["unit"]["title"] == "Genetics"
    assert (await me.get(f"{L}/topics/bio-6.1")).json()["is_bookmarked"] is True
    assert (await other.get(f"{L}/bookmarks")).json() == {"items": [], "total": 0}

    for _ in range(2):
        response = await me.delete(f"{L}/bookmarks/bio-6.1")
        assert response.json()["is_bookmarked"] is False
    assert (await me.get(f"{L}/bookmarks")).json()["total"] == 1
    count = await db_session.execute(
        select(TopicBookmark).where(TopicBookmark.user_id == STUDENT.id)
    )
    assert len(count.scalars().all()) == 1
    assert_error(await me.post(f"{L}/bookmarks/nope"), 404, "TOPIC_NOT_FOUND")
    assert_error(await me.delete(f"{L}/bookmarks/nope"), 404, "TOPIC_NOT_FOUND")


async def test_search(me):
    body = (await me.get(f"{L}/search", params={"q": "mendel"})).json()
    assert [t["title"] for t in body["topics"]] == ["Mendelian inheritance"]
    assert body["topics"][0]["unit"]["number"] == 6
    body = (await me.get(f"{L}/search", params={"q": "GENET"})).json()
    assert [u["title"] for u in body["units"]] == ["Genetics"]
    body = (await me.get(f"{L}/search", params={"q": "50%"})).json()
    assert body == {"units": [], "topics": []}  # % is not a wildcard
    assert_error(await me.get(f"{L}/search", params={"q": "m"}), 422, "VALIDATION_ERROR")
    assert_error(await me.get(f"{L}/search"), 422, "VALIDATION_ERROR")


# --------------------------------------------------------------------------- uploads


def make_docx(text: str) -> bytes:
    import docx

    document = docx.Document()
    for line in text.splitlines():
        document.add_paragraph(line)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


async def _upload(client, name, data, mime, **form):  # type: ignore[no-untyped-def]
    return await client.post(f"{L}/uploads", files={"file": (name, data, mime)}, data=form)


@pytest.mark.parametrize(
    ("name", "mime", "make"),
    [
        ("osmosis notes.pdf", "application/pdf", lambda: make_pdf(OSMOSIS_NOTES)),
        ("osmosis.docx", DOCX, lambda: make_docx(OSMOSIS_NOTES)),
        ("osmosis.txt", "text/plain", lambda: OSMOSIS_NOTES.encode()),
    ],
    ids=["pdf", "docx", "txt"],
)
async def test_upload_summary_and_save_to_short_notes(me, other, upload_dir, name, mime, make):
    response = await _upload(me, name, make(), mime, topic_id="bio-2.8", summary_length="short")
    assert response.status_code == 202, response.text
    accepted = response.json()
    assert accepted["status"] == "queued"
    stored = list(upload_dir.rglob("*"))
    assert any(p.is_file() for p in stored)

    upload = (await me.get(f"{L}/uploads/{accepted['upload_id']}")).json()
    assert (upload["status"], upload["error"], upload["summary_length"]) == ("done", None, "short")
    assert upload["file_name"] == name
    assert upload["summary"] and 5 <= len(upload["key_points"]) <= 10
    assert "water potential" in upload["extracted_text"]
    job = (await me.get(f"{L}/jobs/{accepted['job_id']}")).json()
    assert (job["kind"], job["status"], job["result_id"]) == (
        "upload_summary",
        "done",
        accepted["upload_id"],
    )

    saved = await me.post(f"{L}/uploads/{accepted['upload_id']}/save-to-short-notes")
    assert saved.status_code == 201, saved.text
    note = saved.json()
    assert (note["type"], note["source"], note["is_own"], note["ai_generated"]) == (
        "short",
        "upload",
        True,
        False,
    )
    assert [b["type"] for b in note["blocks"]] == ["heading", "paragraph", "heading", "bullet_list"]
    shown = (await me.get(f"{L}/topics/bio-2.8/notes", params={"type": "short"})).json()
    assert shown["id"] == note["id"]

    # Another student sees none of it.
    uid = accepted["upload_id"]
    assert_error(await other.get(f"{L}/uploads/{uid}"), 404, "UPLOAD_NOT_FOUND")
    assert_error(
        await other.post(f"{L}/uploads/{uid}/save-to-short-notes"), 404, "UPLOAD_NOT_FOUND"
    )
    assert_error(await other.delete(f"{L}/uploads/{uid}"), 404, "UPLOAD_NOT_FOUND")
    assert (await other.get(f"{L}/uploads")).json()["total"] == 0


async def test_upload_list_pagination_and_delete(me, db_session, upload_dir):
    ids = []
    for n in range(3):
        r = await _upload(me, f"n{n}.txt", OSMOSIS_NOTES.encode(), "text/plain")
        ids.append(r.json()["upload_id"])
    page = (await me.get(f"{L}/uploads", params={"page": 1, "size": 2})).json()
    assert (page["total"], len(page["items"]), page["page"], page["size"]) == (3, 2, 1, 2)
    assert page["items"][0]["id"] == ids[-1]  # newest first
    page2 = (await me.get(f"{L}/uploads", params={"page": 2, "size": 2})).json()
    assert [u["id"] for u in page2["items"]] == [ids[0]]

    upload = await db_session.get(Upload, uuid.UUID(ids[0]))
    file = upload_dir / upload.file_path
    assert file.is_file()
    response = await me.delete(f"{L}/uploads/{ids[0]}")
    assert response.status_code == 204
    assert not file.exists()
    assert_error(await me.get(f"{L}/uploads/{ids[0]}"), 404, "UPLOAD_NOT_FOUND")
    assert_error(await me.delete(f"{L}/uploads/{ids[0]}"), 404, "UPLOAD_NOT_FOUND")
    assert (await me.get(f"{L}/uploads")).json()["total"] == 2


async def test_save_to_notes_needs_a_topic(me):
    r = await _upload(me, "n.txt", OSMOSIS_NOTES.encode(), "text/plain")
    uid = r.json()["upload_id"]
    assert_error(await me.post(f"{L}/uploads/{uid}/save-to-short-notes"), 400, "TOPIC_REQUIRED")
    saved = await me.post(f"{L}/uploads/{uid}/save-to-short-notes", json={"topic_id": "bio-2.8"})
    assert saved.status_code == 201
    assert saved.json()["topic_id"] == str((await me.get(f"{L}/topics/bio-2.8")).json()["id"])


@pytest.mark.parametrize(
    ("name", "data", "mime", "status", "code"),
    [
        ("virus.exe", b"MZ....", "application/x-msdownload", 415, "UNSUPPORTED_FILE_TYPE"),
        ("notes.pdf", b"not a pdf at all", "application/pdf", 415, "UNSUPPORTED_FILE_TYPE"),
        ("notes.txt", b"%PDF-1.4", "application/pdf", 415, "UNSUPPORTED_FILE_TYPE"),
        ("notes.txt", b"", "text/plain", 422, "EMPTY_FILE"),
        ("bin.txt", b"\x00\x01\x02binary", "text/plain", 415, "UNSUPPORTED_FILE_TYPE"),
    ],
    ids=["exe", "fake-pdf", "wrong-extension", "empty", "binary-txt"],
)
async def test_upload_rejections(me, upload_dir, name, data, mime, status, code):
    assert_error(await _upload(me, name, data, mime), status, code)
    assert not any(p.is_file() for p in upload_dir.rglob("*"))  # nothing stored


async def test_upload_too_large(me, upload_dir, monkeypatch):
    monkeypatch.setattr(get_api_settings(), "MAX_UPLOAD_MB", 1)
    data = b"a" * (1024 * 1024 + 1)
    assert_error(await _upload(me, "big.txt", data, "text/plain"), 413, "FILE_TOO_LARGE")


async def test_upload_bad_options(me):
    response = await _upload(me, "n.txt", b"hi", "text/plain", summary_length="huge")
    assert_error(response, 422, "VALIDATION_ERROR")
    response = await _upload(me, "n.txt", b"hi", "text/plain", topic_id="nope")
    assert_error(response, 404, "TOPIC_NOT_FOUND")
    assert_error(await me.get(f"{L}/uploads/{uuid.uuid4()}"), 404, "UPLOAD_NOT_FOUND")


async def test_image_without_ocr_fails_clearly(me, monkeypatch):
    monkeypatch.setattr(learn_upload, "ocr_available", lambda: False)
    r = await _upload(me, "page.png", b"\x89PNG\r\n\x1a\n" + b"0" * 20, "image/png")
    assert r.status_code == 202
    upload = (await me.get(f"{L}/uploads/{r.json()['upload_id']}")).json()
    assert upload["status"] == "failed" and upload["error"].startswith("OCR not available")
    job = (await me.get(f"{L}/jobs/{r.json()['job_id']}")).json()
    assert (job["status"], job["error_code"]) == ("failed", "OCR_NOT_AVAILABLE")
    response = await me.post(f"{L}/uploads/{r.json()['upload_id']}/save-to-short-notes")
    assert_error(response, 400, "UPLOAD_NOT_READY")


async def test_filenames_are_sanitised(me):
    r = await _upload(me, "../../etc/pass wd<>.txt", OSMOSIS_NOTES.encode(), "text/plain")
    upload = (await me.get(f"{L}/uploads/{r.json()['upload_id']}")).json()
    assert upload["file_name"] == "pass wd_.txt"


def test_sanitize_filename():
    from api.modules.learn.service import sanitize_filename

    assert sanitize_filename("..\\..\\x.pdf") == "x.pdf"
    assert sanitize_filename("") == "upload"
    assert sanitize_filename("a" * 300 + ".pdf").endswith(".pdf")
    assert len(sanitize_filename("a" * 300 + ".pdf")) == 120
