"""Tests for the admin syllabus manager (/api/v1/admin/syllabus). Owner: Keshomigha."""

import random
import uuid

import pytest
from sqlalchemy import delete, select

from shared.db.base import EMBEDDING_DIM
from shared.db.models import Concept, Misconception, Question, Unit
from shared.enums import QuestionType

BASE = "/api/v1/admin/syllabus"

# --------------------------------------------------------------------------- access + validation


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/units"),
        ("post", "/units"),
        ("patch", f"/units/{uuid.uuid4()}"),
        ("get", f"/units/{uuid.uuid4()}/topics"),
        ("delete", f"/topics/{uuid.uuid4()}"),
        ("post", f"/topics/{uuid.uuid4()}/concepts"),
        ("delete", f"/concepts/{uuid.uuid4()}"),
    ],
)
async def test_students_cannot_use_the_syllabus_manager(client, method, path):
    response = await client.request(method, BASE + path, json={})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_syllabus_manager_requires_login(anon_client):
    assert (await anon_client.get(f"{BASE}/units")).status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"number": 0, "title": "Zero"},  # numbers start at 1
        {"number": 11, "title": ""},  # empty title
        {"number": 11, "title": "Weightless", "exam_weight": 0},
        {"title": "No number"},
    ],
)
async def test_create_unit_validation(admin_client, body):
    response = await admin_client.post(f"{BASE}/units", json=body)
    assert response.status_code == 422


# --------------------------------------------------------------------------- real database


@pytest.fixture
async def unit_number(db_session):
    """A free unit number for this test; the unit (and everything under it) is removed after."""
    number = random.randint(50, 99)
    while (await db_session.execute(select(Unit).where(Unit.number == number))).first():
        number = random.randint(50, 99)
    yield number
    await db_session.execute(delete(Question).where(Question.stem == "Admin test question"))
    await db_session.execute(delete(Misconception).where(Misconception.title == "Admin test"))
    await db_session.execute(delete(Unit).where(Unit.number == number))
    await db_session.commit()


@pytest.mark.db
async def test_create_and_edit_the_syllabus_tree(admin_client, client, unit_number):
    # ---- unit
    created = await admin_client.post(
        f"{BASE}/units", json={"number": unit_number, "title": "Test unit"}
    )
    assert created.status_code == 201, created.text
    unit = created.json()
    assert unit["exam_weight"] == 1.0 and unit["is_outdated"] is False and unit["topic_count"] == 0

    again = await admin_client.post(f"{BASE}/units", json={"number": unit_number, "title": "Dup"})
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "UNIT_NUMBER_TAKEN"

    renamed = await admin_client.patch(
        f"{BASE}/units/{unit['id']}", json={"title": "Renamed unit", "exam_weight": 2.5}
    )
    assert renamed.json()["title"] == "Renamed unit"
    assert renamed.json()["exam_weight"] == 2.5

    # ---- topics
    t2 = await admin_client.post(
        f"{BASE}/units/{unit['id']}/topics",
        json={"number": "T.2", "title": "Second", "order_index": 2},
    )
    t1 = await admin_client.post(
        f"{BASE}/units/{unit['id']}/topics",
        json={"number": "T.1", "title": "First", "order_index": 1},
    )
    assert t1.status_code == t2.status_code == 201
    dup = await admin_client.post(
        f"{BASE}/units/{unit['id']}/topics", json={"number": "T.1", "title": "Dup"}
    )
    assert dup.json()["error"]["code"] == "TOPIC_NUMBER_TAKEN"

    topics = (await admin_client.get(f"{BASE}/units/{unit['id']}/topics")).json()
    assert [t["number"] for t in topics] == ["T.1", "T.2"]

    # ---- concepts
    topic_id = t1.json()["id"]
    code = f"T{unit_number}.1.1"
    concept = await admin_client.post(
        f"{BASE}/topics/{topic_id}/concepts",
        json={"code": code, "name": "Law of segregation", "learning_outcome": "Explain 3:1"},
    )
    assert concept.status_code == 201, concept.text
    dup_code = await admin_client.post(
        f"{BASE}/topics/{topic_id}/concepts", json={"code": code, "name": "Dup"}
    )
    assert dup_code.json()["error"]["code"] == "CONCEPT_CODE_TAKEN"

    concepts = (await admin_client.get(f"{BASE}/topics/{topic_id}/concepts")).json()
    assert [c["name"] for c in concepts] == ["Law of segregation"]

    # ---- the student endpoints see the new tree
    student_topics = (await client.get(f"/api/v1/units/{unit['id']}/topics")).json()
    assert [t["title"] for t in student_topics["topics"]] == ["First", "Second"]
    assert student_topics["topics"][0]["concept_count"] == 1

    # ---- required fields can't be cleared
    cleared = await admin_client.patch(f"{BASE}/units/{unit['id']}", json={"title": None})
    assert cleared.status_code == 400
    assert cleared.json()["error"]["code"] == "FIELD_REQUIRED"


@pytest.mark.db
async def test_mark_outdated_hides_it_from_students(admin_client, client, unit_number):
    unit = (
        await admin_client.post(f"{BASE}/units", json={"number": unit_number, "title": "Old"})
    ).json()
    topic = (
        await admin_client.post(
            f"{BASE}/units/{unit['id']}/topics", json={"number": "T.1", "title": "Old topic"}
        )
    ).json()

    await admin_client.patch(f"{BASE}/topics/{topic['id']}", json={"is_outdated": True})
    student = (await client.get(f"/api/v1/units/{unit['id']}/topics")).json()
    assert student["topics"] == []
    admin_view = (await admin_client.get(f"{BASE}/units/{unit['id']}/topics")).json()
    assert admin_view[0]["is_outdated"] is True  # admins still see it

    await admin_client.patch(f"{BASE}/units/{unit['id']}", json={"is_outdated": True})
    assert unit["id"] not in {u["id"] for u in (await client.get("/api/v1/units")).json()}


@pytest.mark.db
async def test_editing_a_concept_clears_its_embedding(admin_client, db_session, unit_number):
    unit = (
        await admin_client.post(f"{BASE}/units", json={"number": unit_number, "title": "Emb"})
    ).json()
    topic = (
        await admin_client.post(
            f"{BASE}/units/{unit['id']}/topics", json={"number": "T.1", "title": "Topic"}
        )
    ).json()
    concept = (
        await admin_client.post(f"{BASE}/topics/{topic['id']}/concepts", json={"name": "Old"})
    ).json()
    row = await db_session.get(Concept, uuid.UUID(concept["id"]))
    row.embedding = [0.1] * EMBEDDING_DIM
    row.embedding_model = "test-model"
    await db_session.commit()

    # order only: the meaning did not change, the embedding stays
    await admin_client.patch(f"{BASE}/concepts/{concept['id']}", json={"order_index": 3})
    await db_session.refresh(row)
    assert row.embedding is not None

    await admin_client.patch(f"{BASE}/concepts/{concept['id']}", json={"name": "New"})
    await db_session.refresh(row)
    assert row.embedding is None and row.embedding_model is None


@pytest.mark.db
async def test_delete_rules(admin_client, db_session, unit_number):
    unit = (
        await admin_client.post(f"{BASE}/units", json={"number": unit_number, "title": "Del"})
    ).json()
    topic = (
        await admin_client.post(
            f"{BASE}/units/{unit['id']}/topics", json={"number": "T.1", "title": "Topic"}
        )
    ).json()
    used = (
        await admin_client.post(f"{BASE}/topics/{topic['id']}/concepts", json={"name": "Used"})
    ).json()
    free = (
        await admin_client.post(f"{BASE}/topics/{topic['id']}/concepts", json={"name": "Free"})
    ).json()

    # a topic with concepts can't be deleted
    has_concepts = await admin_client.delete(f"{BASE}/topics/{topic['id']}")
    assert has_concepts.status_code == 409
    assert has_concepts.json()["error"]["code"] == "TOPIC_HAS_CONCEPTS"

    # a concept that a misconception points at is in use
    db_session.add(Misconception(concept_id=uuid.UUID(used["id"]), title="Admin test"))
    await db_session.commit()
    in_use = await admin_client.delete(f"{BASE}/concepts/{used['id']}")
    assert in_use.status_code == 409
    assert in_use.json()["error"]["code"] == "IN_USE"

    # an unused concept can be deleted
    assert (await admin_client.delete(f"{BASE}/concepts/{free['id']}")).status_code == 204
    gone = await admin_client.patch(f"{BASE}/concepts/{free['id']}", json={"name": "x"})
    assert gone.json()["error"]["code"] == "CONCEPT_NOT_FOUND"

    # an empty topic that a question points at is in use
    empty = (
        await admin_client.post(
            f"{BASE}/units/{unit['id']}/topics", json={"number": "T.2", "title": "Empty"}
        )
    ).json()
    db_session.add(
        Question(
            topic_id=uuid.UUID(empty["id"]),
            question_type=QuestionType.MCQ,
            stem="Admin test question",
        )
    )
    await db_session.commit()
    topic_in_use = await admin_client.delete(f"{BASE}/topics/{empty['id']}")
    assert topic_in_use.json()["error"]["code"] == "IN_USE"

    # an empty, unused topic can be deleted
    spare = (
        await admin_client.post(
            f"{BASE}/units/{unit['id']}/topics", json={"number": "T.3", "title": "Spare"}
        )
    ).json()
    assert (await admin_client.delete(f"{BASE}/topics/{spare['id']}")).status_code == 204


async def test_unknown_ids_are_not_found(admin_client, monkeypatch):
    from api.modules.syllabus import repository

    async def nothing(session, *args):
        return None

    monkeypatch.setattr(repository, "get_unit", nothing)
    monkeypatch.setattr(repository, "get_topic", nothing)
    monkeypatch.setattr(repository, "get_concept", nothing)
    checks = [
        ("patch", f"/units/{uuid.uuid4()}", "UNIT_NOT_FOUND"),
        ("get", f"/units/{uuid.uuid4()}/topics", "UNIT_NOT_FOUND"),
        ("delete", f"/topics/{uuid.uuid4()}", "TOPIC_NOT_FOUND"),
        ("get", f"/topics/{uuid.uuid4()}/concepts", "TOPIC_NOT_FOUND"),
        ("delete", f"/concepts/{uuid.uuid4()}", "CONCEPT_NOT_FOUND"),
    ]
    for method, path, code in checks:
        response = await admin_client.request(method, BASE + path, json={"title": "x"})
        assert response.status_code == 404, (path, response.text)
        assert response.json()["error"]["code"] == code
