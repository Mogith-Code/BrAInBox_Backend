<<<<<<< Updated upstream
"""Tests for the syllabus module: units, a unit's topics, one topic with its concepts.
Owner: Keshomigha."""

import random
import uuid
from types import SimpleNamespace
=======
"""Tests for the syllabus module: seeding and the Learn navigation endpoints."""

import importlib
import random
import sys
import uuid
from types import ModuleType
>>>>>>> Stashed changes

import pytest
from sqlalchemy import delete

<<<<<<< Updated upstream
from api.modules.syllabus import repository
from shared.db.models import Concept, Topic, Unit

# --------------------------------------------------------------------------- placeholders
=======
from api.modules.syllabus import service
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


# --------------------------------------------------------------------------- placeholder
>>>>>>> Stashed changes


async def test_syllabus_status_requires_login(anon_client):
    response = await anon_client.get("/api/v1/syllabus/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_syllabus_status_placeholder(client):
    response = await client.get("/api/v1/syllabus/status")
    assert response.status_code == 200
    assert response.json() == {"module": "syllabus", "status": "todo"}


<<<<<<< Updated upstream
# --------------------------------------------------------------------------- API (repository faked)

UNIT_ID = uuid.uuid4()
OUTDATED_UNIT_ID = uuid.uuid4()
TOPIC_ID = uuid.uuid4()


def _unit(unit_id=UNIT_ID, number=6, title="Genetics", is_outdated=False):  # type: ignore[no-untyped-def]
    return SimpleNamespace(
        id=unit_id, number=number, title=title, description=None, is_outdated=is_outdated
    )


def _topic(topic_id=TOPIC_ID, number="6.2", title="Mendelian inheritance", is_outdated=False):  # type: ignore[no-untyped-def]
    return SimpleNamespace(
        id=topic_id, number=number, title=title, description="Laws", is_outdated=is_outdated
    )


@pytest.fixture
def fake_repository(monkeypatch):
    units = {UNIT_ID: _unit(), OUTDATED_UNIT_ID: _unit(OUTDATED_UNIT_ID, 99, "Old", True)}

    async def list_units_with_counts(session):
        return [(_unit(uuid.uuid4(), 1, "Introduction to Biology"), 4), (units[UNIT_ID], 2)]

    async def get_unit(session, unit_id):
        return units.get(unit_id)

    async def list_topics_with_counts(session, unit_id):
        return [(_topic(), 3), (_topic(uuid.uuid4(), "6.3", "Dihybrid crosses"), 0)]

    async def get_topic_with_unit(session, topic_id):
        return (_topic(), units[UNIT_ID]) if topic_id == TOPIC_ID else None

    async def list_concepts(session, topic_id):
        return [
            SimpleNamespace(
                id=uuid.uuid4(),
                code="6.2.1",
                name="Law of segregation",
                description=None,
                learning_outcome="Explain the 3:1 ratio",
            )
        ]

    monkeypatch.setattr(repository, "list_current_units_with_topic_counts", list_units_with_counts)
    monkeypatch.setattr(repository, "get_unit", get_unit)
    monkeypatch.setattr(
        repository, "list_current_topics_with_concept_counts", list_topics_with_counts
    )
    monkeypatch.setattr(repository, "get_topic_with_unit", get_topic_with_unit)
    monkeypatch.setattr(repository, "list_current_concepts", list_concepts)


@pytest.mark.parametrize(
    "path",
    ["/api/v1/units", f"/api/v1/units/{UNIT_ID}/topics", f"/api/v1/topics/{TOPIC_ID}"],
)
async def test_syllabus_endpoints_require_login(anon_client, path):
    response = await anon_client.get(path)
    assert response.status_code == 401


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


async def test_unit_topics(client, fake_repository):
    response = await client.get(f"/api/v1/units/{UNIT_ID}/topics")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["unit"]["title"] == "Genetics"
    assert body["unit"]["topic_count"] == 2  # matches the topics returned
    assert [t["number"] for t in body["topics"]] == ["6.2", "6.3"]
    assert body["topics"][0]["concept_count"] == 3
    assert body["topics"][1]["concept_count"] == 0


async def test_unit_topics_unknown_unit(client, fake_repository):
    response = await client.get(f"/api/v1/units/{uuid.uuid4()}/topics")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "UNIT_NOT_FOUND"


async def test_unit_topics_outdated_unit_is_not_found(client, fake_repository):
    response = await client.get(f"/api/v1/units/{OUTDATED_UNIT_ID}/topics")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "UNIT_NOT_FOUND"


async def test_topic_detail(client, fake_repository):
    response = await client.get(f"/api/v1/topics/{TOPIC_ID}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "Mendelian inheritance"
    assert body["is_outdated"] is False
    assert body["unit"] == {"id": str(UNIT_ID), "number": 6, "title": "Genetics"}
    assert body["concepts"][0]["code"] == "6.2.1"
    assert body["concepts"][0]["learning_outcome"] == "Explain the 3:1 ratio"


async def test_topic_detail_unknown_topic(client, fake_repository):
    response = await client.get(f"/api/v1/topics/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TOPIC_NOT_FOUND"


@pytest.mark.parametrize("path", ["/api/v1/units/abc/topics", "/api/v1/topics/abc"])
async def test_bad_ids_are_rejected(client, path):
    response = await client.get(path)
    assert response.status_code == 422


# --------------------------------------------------------------------------- real queries (DB)


@pytest.fixture
async def syllabus_data(db_session):
    """One unit with a current topic (2 current concepts + 1 outdated) and an outdated topic;
    plus an outdated unit. Everything is removed afterwards."""
    base = random.randint(100_000, 999_000)
    unit = Unit(number=base, title="Test unit")
    old_unit = Unit(number=base + 1, title="Old test unit", is_outdated=True)
    db_session.add_all([unit, old_unit])
    await db_session.flush()
    topic = Topic(unit_id=unit.id, number="T.2", title="Current topic", order_index=2)
    first = Topic(unit_id=unit.id, number="T.1", title="First topic", order_index=1)
    old_topic = Topic(unit_id=unit.id, number="T.9", title="Old topic", is_outdated=True)
    db_session.add_all([topic, first, old_topic])
    await db_session.flush()
    db_session.add_all(
        [
            Concept(topic_id=topic.id, name="Second concept", order_index=2),
            Concept(topic_id=topic.id, name="First concept", order_index=1),
            Concept(topic_id=topic.id, name="Old concept", is_outdated=True),
        ]
    )
    await db_session.commit()
    yield SimpleNamespace(unit=unit, old_unit=old_unit, topic=topic, old_topic=old_topic)
    await db_session.execute(delete(Unit).where(Unit.id.in_([unit.id, old_unit.id])))
=======
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
    assert service.unit_status(progress) == expected


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
    "path", ["/api/v1/subjects/biology/units", "/api/v1/units/u1/topics", "/api/v1/topics/bio-1.1"]
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
>>>>>>> Stashed changes
    await db_session.commit()


@pytest.mark.db
<<<<<<< Updated upstream
async def test_syllabus_tree_from_the_database(client, syllabus_data):
    units = (await client.get("/api/v1/units")).json()
    mine = [u for u in units if u["id"] == str(syllabus_data.unit.id)]
    assert mine and mine[0]["topic_count"] == 2  # the outdated topic is not counted
    assert str(syllabus_data.old_unit.id) not in {u["id"] for u in units}

    topics = (await client.get(f"/api/v1/units/{syllabus_data.unit.id}/topics")).json()
    assert [t["title"] for t in topics["topics"]] == ["First topic", "Current topic"]
    assert topics["topics"][1]["concept_count"] == 2

    old = await client.get(f"/api/v1/units/{syllabus_data.old_unit.id}/topics")
    assert old.status_code == 404

    detail = (await client.get(f"/api/v1/topics/{syllabus_data.topic.id}")).json()
    assert [c["name"] for c in detail["concepts"]] == ["First concept", "Second concept"]
    assert detail["unit"]["title"] == "Test unit"

    outdated = (await client.get(f"/api/v1/topics/{syllabus_data.old_topic.id}")).json()
    assert outdated["is_outdated"] is True
=======
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
>>>>>>> Stashed changes
