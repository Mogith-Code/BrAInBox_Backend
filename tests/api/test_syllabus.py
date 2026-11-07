"""Tests for the syllabus module: the unit list, seeding and the Learn navigation endpoints."""

import importlib
import random
import sys
import uuid
from types import ModuleType, SimpleNamespace

import pytest
from sqlalchemy import delete

from api.modules.syllabus import repository, service
from api.modules.syllabus.schemas import TopicOut
from shared.db.models import Concept, Subject, Topic, Unit, User, UserTopicProgress
from shared.enums import TopicProgressStatus, UserRole
from tests.conftest import STUDENT

SCRIPTS_DIR = "scripts"


def seed_script() -> ModuleType:
    """scripts/seed_syllabus.py (scripts/ is not a package, so put it on sys.path first)."""
    if SCRIPTS_DIR not in sys.path:
        sys.path.insert(0, SCRIPTS_DIR)
    return importlib.import_module("seed_syllabus")


# --------------------------------------------------------------------------- removed placeholder


async def test_syllabus_status_placeholder_is_gone(client):
    assert (await client.get("/api/v1/syllabus/status")).status_code == 404


# --------------------------------------------------------------------------- GET /units (repository faked)

UNIT_ID = uuid.uuid4()


def _unit(unit_id=UNIT_ID, number=6, title="Genetics"):  # type: ignore[no-untyped-def]
    return SimpleNamespace(id=unit_id, number=number, title=title, description=None)


@pytest.fixture
def fake_repository(monkeypatch):
    async def list_units_with_counts(session):
        return [(_unit(uuid.uuid4(), 1, "Introduction to Biology"), 4), (_unit(), 2)]

    monkeypatch.setattr(repository, "list_current_units_with_topic_counts", list_units_with_counts)


async def test_list_units(client, fake_repository):
    response = await client.get("/api/v1/units")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [u["number"] for u in body] == [1, 6]  # Unit 1 first
    assert body[1] == {
        "id": str(UNIT_ID),
        "number": 6,
        "title": "Genetics",
        "description": None,
        "topic_count": 2,
    }


# --------------------------------------------------------------------------- seed file


def test_syllabus_file_has_10_units_64_topics_216_subtopics():
    seed = seed_script()
    data = seed.load_syllabus(seed.DEFAULT_FILE)
    counts = seed.count_syllabus(data)
    assert (counts.units, counts.topics, counts.subtopics) == (10, 64, 216)
    assert seed.code_prefix(data["subject"]) == "bio"


def test_load_syllabus_rejects_duplicate_topic_codes(tmp_path):
    path = tmp_path / "syllabus.json"
    path.write_text(
        '{"subject": {"id": "biology", "name": "Biology", "level": "A/L"}, "units": ['
        '{"id": "u1", "number": 1, "title": "U", "topics": ['
        '{"code": "1.1", "title": "A", "subtopics": []},'
        '{"code": "1.1", "title": "B", "subtopics": []}]}]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="1.1"):
        seed_script().load_syllabus(path)


@pytest.mark.db
async def test_seed_syllabus_is_idempotent():
    seed = seed_script()
    first = await seed.seed(seed.DEFAULT_FILE)
    second = await seed.seed(seed.DEFAULT_FILE)
    assert (first.units, first.topics, first.subtopics) == (10, 64, 216)
    assert second == first


# --------------------------------------------------------------------------- pure helpers


@pytest.mark.parametrize(
    ("progress", "expected"),
    [
        (100, "strong"),
        (75, "strong"),
        (74, "improving"),
        (40, "improving"),
        (39, "weak"),
        (0, "weak"),
    ],
)
def test_unit_status_thresholds(progress, expected):
    assert service.unit_status(progress, started=True) == expected


def test_unit_without_activity_is_not_started():
    assert service.unit_status(0, started=False) == "not_started"


def test_parse_ref_accepts_uuid_or_code():
    some_id = uuid.uuid4()
    assert service.parse_ref(str(some_id)) == some_id
    assert service.parse_ref("bio-6.1") == "bio-6.1"


def test_summarise_topics_counts_mastered_and_weak():
    def topic(status: TopicProgressStatus, is_weak: bool) -> TopicOut:
        return TopicOut(
            id="bio-1.1",
            uuid=uuid.uuid4(),
            code="1.1",
            title="T",
            order=1,
            status=status,
            progress_pct=0,
            is_weak=is_weak,
            subtopics=[],
        )

    summary = service.summarise_topics(
        [
            topic(TopicProgressStatus.MASTERED, False),
            topic(TopicProgressStatus.MASTERED, False),
            topic(TopicProgressStatus.IN_PROGRESS, True),
            topic(TopicProgressStatus.NOT_STARTED, False),
        ]
    )
    assert (summary.mastered, summary.weak) == (2, 1)


# --------------------------------------------------------------------------- endpoints: auth


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/units",
        "/api/v1/subjects/biology/units",
        "/api/v1/units/u1/topics",
        "/api/v1/topics/bio-1.1",
    ],
)
async def test_learn_endpoints_require_login(anon_client, path):
    response = await anon_client.get(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


# --------------------------------------------------------------------------- endpoints (DB)


@pytest.fixture
async def learn_data(db_session):
    """A throw-away subject with one unit, two topics (with sub-topics) and the student's
    progress on the first topic. Everything is removed afterwards."""
    suffix = uuid.uuid4().hex[:8]
    if await db_session.get(User, STUDENT.id) is None:
        db_session.add(
            User(id=STUDENT.id, firebase_uid=STUDENT.firebase_uid, role=UserRole.STUDENT)
        )
    subject = Subject(code=f"test-{suffix}", name="Test subject", level="A/L")
    db_session.add(subject)
    await db_session.flush()
    unit = Unit(
        subject_id=subject.id,
        code=f"tu-{suffix}",
        number=random.randint(1000, 999_999),
        title="Test unit",
        periods=12,
        icon="dna",
    )
    db_session.add(unit)
    await db_session.flush()
    first = Topic(unit_id=unit.id, code=f"t-{suffix}-1", number="T.1", title="First", order_index=1)
    second = Topic(
        unit_id=unit.id, code=f"t-{suffix}-2", number="T.2", title="Second", order_index=2
    )
    db_session.add_all([first, second])
    await db_session.flush()
    db_session.add_all(
        [
            Concept(topic_id=first.id, code=f"t-{suffix}-1.2", name="Sub B", order_index=2),
            Concept(topic_id=first.id, code=f"t-{suffix}-1.1", name="Sub A", order_index=1),
            Concept(topic_id=second.id, code=f"t-{suffix}-2.1", name="Sub C", order_index=1),
            UserTopicProgress(
                user_id=STUDENT.id,
                topic_id=first.id,
                status=TopicProgressStatus.MASTERED,
                score=90,
                is_weak=False,
            ),
        ]
    )
    await db_session.commit()
    yield {"subject": subject, "unit": unit, "first": first, "second": second, "suffix": suffix}
    for stmt in (
        delete(Subject).where(Subject.id == subject.id),  # units, topics, progress cascade
        delete(User).where(User.id == STUDENT.id),
    ):
        await db_session.execute(stmt)
    await db_session.commit()


@pytest.mark.db
async def test_list_units_with_progress(client, learn_data):
    response = await client.get(f"/api/v1/subjects/{learn_data['subject'].code}/units")
    assert response.status_code == 200, response.text
    assert response.json() == [
        {
            "id": learn_data["unit"].code,
            "uuid": str(learn_data["unit"].id),
            "number": learn_data["unit"].number,
            "title": "Test unit",
            "periods": 12,
            "icon": "dna",
            "topicCount": 2,
            "progressPct": 45,  # (90 + 0) / 2
            "status": "improving",
        }
    ]


@pytest.mark.db
async def test_unit_with_no_activity_is_not_started_in_both_lists(client, db_session, learn_data):
    await db_session.execute(
        delete(UserTopicProgress).where(UserTopicProgress.user_id == STUDENT.id)
    )
    await db_session.commit()

    units = (await client.get(f"/api/v1/subjects/{learn_data['subject'].code}/units")).json()
    assert (units[0]["status"], units[0]["progressPct"]) == ("not_started", 0)

    body = (await client.get(f"/api/v1/units/{learn_data['unit'].code}/topics")).json()
    assert (body["unit"]["status"], body["unit"]["progressPct"]) == ("not_started", 0)
    assert {t["status"] for t in body["topics"]} == {"not_started"}


@pytest.mark.db
async def test_another_students_progress_does_not_start_my_unit(client, db_session, learn_data):
    """Progress of other students must never leak into my unit status."""
    other_id = uuid.uuid4()
    db_session.add(User(id=other_id, firebase_uid=f"other-{other_id}", role=UserRole.STUDENT))
    await db_session.execute(
        delete(UserTopicProgress).where(UserTopicProgress.user_id == STUDENT.id)
    )
    await db_session.flush()
    db_session.add(
        UserTopicProgress(
            user_id=other_id,
            topic_id=learn_data["first"].id,
            status=TopicProgressStatus.MASTERED,
            score=100,
        )
    )
    await db_session.commit()
    try:
        units = (await client.get(f"/api/v1/subjects/{learn_data['subject'].code}/units")).json()
        assert (units[0]["status"], units[0]["progressPct"]) == ("not_started", 0)
    finally:
        await db_session.execute(delete(User).where(User.id == other_id))
        await db_session.commit()


@pytest.mark.db
async def test_list_unit_topics_with_subtopics_and_summary(client, learn_data):
    response = await client.get(f"/api/v1/units/{learn_data['unit'].code}/topics")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["unit"]["progressPct"] == 45
    assert body["summary"] == {"mastered": 1, "weak": 0}

    first, second = body["topics"]
    suffix = learn_data["suffix"]
    assert first == {
        "id": f"t-{suffix}-1",
        "uuid": str(learn_data["first"].id),
        "code": "T.1",
        "title": "First",
        "order": 1,
        "status": "mastered",
        "progressPct": 90,
        "isWeak": False,
        "subtopics": [
            {"id": f"t-{suffix}-1.1", "title": "Sub A"},
            {"id": f"t-{suffix}-1.2", "title": "Sub B"},
        ],
    }
    # No progress row yet -> not started
    assert (second["status"], second["progressPct"], second["isWeak"]) == ("not_started", 0, False)
    assert second["subtopics"] == [{"id": f"t-{suffix}-2.1", "title": "Sub C"}]


@pytest.mark.db
async def test_get_topic_by_code_or_uuid(client, learn_data):
    by_code = await client.get(f"/api/v1/topics/{learn_data['first'].code}")
    by_uuid = await client.get(f"/api/v1/topics/{learn_data['first'].id}")
    assert by_code.status_code == 200, by_code.text
    assert by_code.json() == by_uuid.json()
    body = by_code.json()
    assert body["unitId"] == learn_data["unit"].code
    assert body["unitTitle"] == "Test unit"
    assert [s["title"] for s in body["subtopics"]] == ["Sub A", "Sub B"]
    assert body["status"] == "mastered"


@pytest.mark.db
@pytest.mark.parametrize(
    ("path", "code"),
    [
        ("/api/v1/subjects/no-such-subject/units", "SUBJECT_NOT_FOUND"),
        ("/api/v1/units/no-such-unit/topics", "UNIT_NOT_FOUND"),
        (f"/api/v1/topics/{uuid.uuid4()}", "TOPIC_NOT_FOUND"),
    ],
)
async def test_learn_endpoints_404(client, path, code):
    response = await client.get(path)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == code


@pytest.mark.db
async def test_outdated_rows_are_hidden_from_learn(client, db_session, learn_data):
    suffix = learn_data["suffix"]
    unit, first = learn_data["unit"], learn_data["first"]
    old_topic = Topic(
        unit_id=unit.id, code=f"t-{suffix}-9", number="T.9", title="Old", is_outdated=True
    )
    old_unit = Unit(
        subject_id=learn_data["subject"].id,
        code=f"ou-{suffix}",
        number=random.randint(1_000_000, 1_999_999),
        title="Old unit",
        is_outdated=True,
    )
    db_session.add_all([old_topic, old_unit])
    await db_session.flush()
    db_session.add(
        Concept(topic_id=first.id, code=f"t-{suffix}-1.9", name="Old sub", is_outdated=True)
    )
    old_topic_id, old_topic_code, old_unit_code = old_topic.id, old_topic.code, old_unit.code
    await db_session.commit()

    units = (await client.get(f"/api/v1/subjects/{learn_data['subject'].code}/units")).json()
    assert [u["id"] for u in units] == [unit.code]
    assert units[0]["topicCount"] == 2  # the outdated topic is not counted

    topics = (await client.get(f"/api/v1/units/{unit.code}/topics")).json()["topics"]
    assert old_topic_code not in {t["id"] for t in topics}
    assert [s["title"] for s in topics[0]["subtopics"]] == ["Sub A", "Sub B"]

    assert (await client.get(f"/api/v1/units/{old_unit_code}/topics")).status_code == 404

    # An outdated topic can still be opened: old notes and questions link to it.
    detail = (await client.get(f"/api/v1/topics/{old_topic_id}")).json()
    assert detail["isOutdated"] is True
