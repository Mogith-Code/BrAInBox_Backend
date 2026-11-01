"""Tests for the syllabus module: units, a unit's topics, one topic with its concepts.
Owner: Keshomigha."""

import random
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete

from api.modules.syllabus import repository
from shared.db.models import Concept, Topic, Unit

# --------------------------------------------------------------------------- placeholders


async def test_syllabus_status_requires_login(anon_client):
    response = await anon_client.get("/api/v1/syllabus/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_syllabus_status_placeholder(client):
    response = await client.get("/api/v1/syllabus/status")
    assert response.status_code == 200
    assert response.json() == {"module": "syllabus", "status": "todo"}


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
    await db_session.commit()


@pytest.mark.db
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
