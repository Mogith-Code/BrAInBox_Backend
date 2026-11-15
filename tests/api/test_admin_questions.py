"""Admin question bank + editor (questions_admin.py). Owner: Udith."""

import uuid

import pytest
from sqlalchemy import delete, select

from api.modules.questions.schemas import AdminOption
from api.modules.questions.service import missing_for_publish
from shared.db.models import (
    Attempt,
    Concept,
    MCQOption,
    Misconception,
    Paper,
    Question,
    Response,
    Topic,
    Unit,
)
from shared.enums import ContentStatus, Difficulty, QuestionType
from tests.conftest import ADMIN

URL = "/api/v1/admin/questions"


def options(*, correct: str = "A", missing_misconception: str | None = None) -> list[dict]:
    rows = []
    for label in "ABCDE":
        row = {"label": label, "text": f"Option {label}", "is_correct": label == correct}
        if label != correct and label != missing_misconception:
            row["misconception"] = f"Thinks {label} is right"
        rows.append(row)
    return rows


@pytest.fixture
async def bank(db_session, admin_in_db):  # type: ignore[no-untyped-def]
    """A unit + topic + concept, and three questions: AI MCQ, past-paper structured, archived."""
    unit = Unit(number=500_000 + uuid.uuid4().int % 99_999, title="Genetics")
    other = Unit(number=400_000 + uuid.uuid4().int % 99_999, title="Evolution")
    db_session.add_all([unit, other])
    await db_session.flush()
    topic = Topic(unit_id=unit.id, number="6.1", title="Mendelian inheritance")
    db_session.add(topic)
    await db_session.flush()
    concept = Concept(topic_id=topic.id, code=f"c-{uuid.uuid4().hex[:8]}", name="Monohybrid cross")
    db_session.add(concept)
    ai = Question(unit_id=unit.id, topic_id=topic.id, question_type=QuestionType.MCQ,
                  difficulty=Difficulty.HARD, stem="Which ratio?", source="ai",
                  status=ContentStatus.PENDING_REVIEW)  # fmt: skip
    past = Question(unit_id=unit.id, topic_id=topic.id, question_type=QuestionType.STRUCTURED,
                    stem="Explain linkage.", source="past_paper", year=2019,
                    status=ContentStatus.APPROVED)  # fmt: skip
    gone = Question(unit_id=unit.id, question_type=QuestionType.MCQ, stem="Old", source="admin",
                    status=ContentStatus.ARCHIVED)  # fmt: skip
    db_session.add_all([ai, past, gone])
    await db_session.flush()
    db_session.add_all(
        [
            MCQOption(question_id=ai.id, label="A", text="3:1", is_correct=True),
            MCQOption(question_id=ai.id, label="B", text="1:1", is_correct=False),
        ]
    )
    await db_session.commit()
    ids = {"unit": unit.id, "unit_number": unit.number, "other_unit": other.id,
           "topic": topic.id, "concept": concept.id, "ai": ai.id, "past": past.id,
           "gone": gone.id}  # fmt: skip
    yield ids
    await db_session.rollback()
    unit_ids = [ids["unit"], ids["other_unit"]]
    await db_session.execute(delete(Paper).where(Paper.created_by == ADMIN.id))
    await db_session.execute(delete(Question).where(Question.unit_id.in_(unit_ids)))
    await db_session.execute(
        delete(Misconception).where(Misconception.concept_id == ids["concept"])
    )
    await db_session.execute(delete(Unit).where(Unit.id.in_(unit_ids)))
    await db_session.commit()


def body(bank: dict, **changes) -> dict:  # type: ignore[no-untyped-def]
    return {
        "stem": "In a monohybrid cross, what ratio appears in the F2?",
        "type": "mcq",
        "difficulty": "easy",
        "unit_id": str(bank["unit"]),
        "topic_id": str(bank["topic"]),
        "concept_id": str(bank["concept"]),
        "explanation": "3 dominant : 1 recessive",
        "status": "draft",
        "is_ai_generated": False,
        "options": options(),
        **changes,
    }


# --------------------------------------------------------------------------- pure rule


def test_publish_rule_lists_every_problem() -> None:
    opts = [
        AdminOption(label="A", text="x", is_correct=True),
        AdminOption(label="B", text="", is_correct=True),
        AdminOption(label="C", text="y", misconception="  "),
    ]
    fields = [p["field"] for p in missing_for_publish("mcq", "Q?", opts)]
    assert fields == ["options", "options.B.text", "options.C.misconception"]
    assert missing_for_publish("essay", "Discuss.", []) == []


# --------------------------------------------------------------------------- auth + validation


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", URL, None),
        ("post", f"{URL}/bulk", {"ids": [str(uuid.uuid4())], "action": "approve"}),
        ("get", f"{URL}/{uuid.uuid4()}", None),
        ("post", URL, {"stem": "x"}),
        ("put", f"{URL}/{uuid.uuid4()}", {"stem": "x"}),
    ],
)
async def test_login_and_admin_role_needed(anon_client, client, method, path, payload) -> None:  # type: ignore[no-untyped-def]
    kwargs = {"json": payload} if payload is not None else {}
    assert (await getattr(anon_client, method)(path, **kwargs)).status_code == 401
    assert (await getattr(client, method)(path, **kwargs)).status_code == 403


@pytest.mark.parametrize(
    "query", ["type=quiz", "difficulty=extreme", "status=gone", "page_size=500", "unit=x"]
)
async def test_bad_filters_are_422(admin_client, query: str) -> None:
    assert (await admin_client.get(f"{URL}?{query}")).status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        {"ids": [], "action": "approve"},
        {"ids": [str(uuid.uuid4())], "action": "publish"},
        {"ids": ["nope"], "action": "delete"},
    ],
)
async def test_bad_bulk_is_422(admin_client, payload: dict) -> None:
    assert (await admin_client.post(f"{URL}/bulk", json=payload)).status_code == 422


@pytest.mark.parametrize(
    "changes",
    [
        {"stem": ""},
        {"type": "quiz"},
        {"status": "published"},
        {"options": [{"label": "A", "text": "x"}, {"label": "A", "text": "y"}]},
        {"options": [{"label": "F", "text": "x"}]},
    ],
)
async def test_bad_question_body_is_422(admin_client, changes: dict) -> None:
    payload = {"stem": "Q?", "type": "mcq", **changes}
    response = await admin_client.post(URL, json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_fixed_paths_are_not_read_as_ids(admin_client) -> None:
    """/bulk is a POST route before /{question_id}; a GET of it is not a 404 'bad id' trap."""
    response = await admin_client.get(f"{URL}/not-a-uuid")
    assert response.status_code == 422


# --------------------------------------------------------------------------- list


@pytest.mark.db
async def test_list_shape_filters_and_past_paper_percent(admin_client, bank) -> None:  # type: ignore[no-untyped-def]
    response = await admin_client.get(URL, params={"unit": bank["unit_number"]})

    assert response.status_code == 200
    page = response.json()
    assert set(page) == {"items", "total", "past_paper_percent"}
    assert page["total"] == 2  # the archived one is hidden
    assert page["past_paper_percent"] == 50
    by_id = {q["id"]: q for q in page["items"]}
    ai = by_id[str(bank["ai"])]
    assert set(ai) == {
        "id", "code", "stem", "unit_number", "topic_title", "type", "difficulty", "source_year",
        "is_ai_generated", "status",
    }  # fmt: skip
    assert ai["code"].startswith("Q-") and ai["code"][2:].isdigit()
    assert (ai["is_ai_generated"], ai["status"], ai["difficulty"]) == (
        True,
        "pending_review",
        "hard",
    )
    assert ai["topic_title"] == "Mendelian inheritance"
    assert by_id[str(bank["past"])]["source_year"] == 2019

    async def count(**params):  # type: ignore[no-untyped-def]
        params["unit"] = bank["unit_number"]
        return (await admin_client.get(URL, params=params)).json()["total"]

    assert await count(type="structured") == 1
    assert await count(difficulty="hard") == 1
    assert await count(status="archived") == 1
    assert await count(page_size=1, page=2) == 2


# --------------------------------------------------------------------------- editor


@pytest.mark.db
async def test_create_get_and_update(admin_client, bank, db_session) -> None:  # type: ignore[no-untyped-def]
    created = await admin_client.post(URL, json=body(bank))
    assert created.status_code == 201, created.text
    question = created.json()
    assert set(question) == {
        "id", "code", "stem", "type", "difficulty", "unit_id", "topic_id", "concept_id",
        "explanation", "status", "is_ai_generated", "options",
    }  # fmt: skip
    assert question["concept_id"] == str(bank["concept"])
    assert [o["misconception"] for o in question["options"]][:2] == [None, "Thinks B is right"]

    loaded = await admin_client.get(f"{URL}/{question['id']}")
    assert loaded.json() == question

    new_options = options(correct="C")
    published = await admin_client.put(
        f"{URL}/{question['id']}", json=body(bank, status="approved", options=new_options[:4])
    )
    assert published.status_code == 200, published.text
    saved = published.json()
    assert saved["status"] == "approved"
    assert [o["label"] for o in saved["options"]] == ["A", "B", "C", "D"]
    assert [o["is_correct"] for o in saved["options"]] == [False, False, True, False]
    assert saved["options"][0]["misconception"] == "Thinks A is right"
    # Each misconception text is stored once (MCQ mapping tables); older ones are kept
    titles = (
        (
            await db_session.execute(
                select(Misconception.title).where(Misconception.concept_id == bank["concept"])
            )
        )
        .scalars()
        .all()
    )
    assert sorted(titles) == [f"Thinks {x} is right" for x in "ABCDE"]


@pytest.mark.db
async def test_publish_needs_one_correct_and_misconceptions(admin_client, bank) -> None:  # type: ignore[no-untyped-def]
    response = await admin_client.post(
        URL, json=body(bank, status="approved", options=options(missing_misconception="D"))
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "QUESTION_INCOMPLETE"
    assert error["details"] == [
        {
            "field": "options.D.misconception",
            "message": "Say which misconception leads to this wrong answer",
        }
    ]


@pytest.mark.db
async def test_syllabus_placement_is_checked(admin_client, bank) -> None:  # type: ignore[no-untyped-def]
    wrong_unit = await admin_client.post(URL, json=body(bank, unit_id=str(bank["other_unit"])))
    unknown_topic = await admin_client.post(
        URL, json=body(bank, topic_id=str(uuid.uuid4()), concept_id=None)
    )
    only_topic = await admin_client.post(URL, json=body(bank, unit_id=None, concept_id=None))

    assert wrong_unit.status_code == 422
    assert wrong_unit.json()["error"]["code"] == "SYLLABUS_MISMATCH"
    assert unknown_topic.status_code == 404
    assert unknown_topic.json()["error"]["code"] == "TOPIC_NOT_FOUND"
    assert only_topic.json()["unit_id"] == str(bank["unit"])  # filled in from the topic


@pytest.mark.db
async def test_unknown_question_is_404(admin_client, bank) -> None:  # type: ignore[no-untyped-def]
    some = uuid.uuid4()
    assert (await admin_client.get(f"{URL}/{some}")).json()["error"]["code"] == "QUESTION_NOT_FOUND"
    assert (await admin_client.put(f"{URL}/{some}", json=body(bank))).status_code == 404
    bulk = await admin_client.post(f"{URL}/bulk", json={"ids": [str(some)], "action": "delete"})
    assert bulk.status_code == 404


# --------------------------------------------------------------------------- bulk


@pytest.mark.db
async def test_bulk_approve_is_all_or_nothing(admin_client, bank, db_session) -> None:  # type: ignore[no-untyped-def]
    # The AI MCQ's wrong option B has no misconception, so it can't be published.
    response = await admin_client.post(
        f"{URL}/bulk", json={"ids": [str(bank["ai"]), str(bank["past"])], "action": "approve"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "QUESTION_INCOMPLETE"
    row = await db_session.get(Question, bank["ai"], populate_existing=True)
    assert row.status == ContentStatus.PENDING_REVIEW


@pytest.mark.db
async def test_bulk_mark_outdated_and_delete(admin_client, bank, db_session) -> None:  # type: ignore[no-untyped-def]
    # The past-paper question was answered by a student, so delete only archives it.
    paper = Paper(title="Practice", created_by=ADMIN.id)
    db_session.add(paper)
    await db_session.flush()
    attempt = Attempt(paper_id=paper.id, user_id=ADMIN.id)
    db_session.add(attempt)
    await db_session.flush()
    db_session.add(Response(attempt_id=attempt.id, question_id=bank["past"]))
    await db_session.commit()

    outdated = await admin_client.post(
        f"{URL}/bulk", json={"ids": [str(bank["ai"])], "action": "mark_outdated"}
    )
    deleted = await admin_client.post(
        f"{URL}/bulk", json={"ids": [str(bank["ai"]), str(bank["past"])], "action": "delete"}
    )

    assert (outdated.status_code, deleted.status_code) == (204, 204)
    assert await db_session.get(Question, bank["ai"], populate_existing=True) is None
    past = await db_session.get(Question, bank["past"], populate_existing=True)
    assert past.status == ContentStatus.ARCHIVED
