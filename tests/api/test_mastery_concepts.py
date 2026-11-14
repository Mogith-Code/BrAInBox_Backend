"""Tests for after_attempt_marked / update_mastery and GET /insights/concepts. Owner: Keshomigha."""

import uuid

import pytest
from sqlalchemy import func, select

from api.modules.performance import repository, service
from api.modules.performance.grading import mastery_percent
from api.modules.performance.repository import ConceptInfo
from shared.db.models import Concept, ConceptMastery, Mistake, QuestionConcept, UnitMastery
from shared.enums import MasterySource
from tests.api.test_exams import FakeAIClient, _app_with, exam_data  # noqa: F401 (fixture)
from tests.api.test_performance import CELLS, GENETICS, Rows
from tests.conftest import STUDENT, _client

UNIT_A, UNIT_B = uuid.uuid4(), uuid.uuid4()

# --------------------------------------------------------------------------- the shared formula


@pytest.mark.parametrize(
    ("correct", "asked", "expected"),
    [(1, 1, 75), (0, 1, 25), (0, 0, 50), (10, 10, 95), (2, 4, 50)],
)
def test_mastery_percent(correct, asked, expected):
    assert mastery_percent(correct, asked) == expected


# --------------------------------------------------------------------------- unit snapshots


def test_unit_snapshot_per_unit_from_one_attempt():
    rows = Rows()
    for correct in (True, True, False):
        rows.add(GENETICS, correct).unit_id = UNIT_A
    rows.add(GENETICS, None, answered=False).unit_id = UNIT_A  # unanswered: asked, wrong
    rows.add(
        GENETICS, False, option_of_other_question=True
    ).unit_id = UNIT_A  # unreliable: left out
    rows.add(CELLS, True).unit_id = UNIT_B
    rows.add(None, False)  # no syllabus unit: skipped
    # unit A: 2 correct of 4 asked -> (2.5 / 5) = 50; unit B: 1 of 1 -> 75
    assert service.unit_snapshots(rows.rows) == {UNIT_A: 50, UNIT_B: 75}


def test_no_answers_no_snapshot():
    assert service.unit_snapshots([]) == {}


# --------------------------------------------------------------------------- concept tallies


def test_concept_tallies_count_valid_answers_for_every_linked_concept():
    c1, c2 = uuid.uuid4(), uuid.uuid4()
    rows = Rows()
    both = rows.add(GENETICS, True)  # linked to both concepts
    wrong = rows.add(GENETICS, False)
    skipped = rows.add(GENETICS, None, answered=False)  # unanswered: not counted
    rows.add(GENETICS, True)  # not linked to any concept
    links = {both.question_id: [c1, c2], wrong.question_id: [c1], skipped.question_id: [c2]}
    tallies = service.concept_tallies(rows.rows, links)
    assert (tallies[c1].correct, tallies[c1].attempted) == (1, 2)
    assert (tallies[c2].correct, tallies[c2].attempted) == (1, 1)
    assert tallies[c1].last_at == wrong.created_at  # the newest answer


def test_concept_mastery_rows_use_the_table_scale():
    concept = uuid.uuid4()
    tallies = {concept: service.Tally(correct=1, attempted=1)}
    [row] = service.concept_mastery_rows(STUDENT.id, tallies)
    assert row["mastery_score"] == 0.75  # 0-1 in concept_mastery
    assert (row["attempts_count"], row["correct_count"]) == (1, 1)


# --------------------------------------------------------------------------- concept insights


def _info(name: str, code: str) -> ConceptInfo:
    return ConceptInfo(
        id=uuid.uuid4(),
        code=code,
        name=name,
        topic_id=uuid.uuid4(),
        topic="Genetics",
        unit_number=6,
        unit="Genetics",
    )


def test_concept_insights_rank_and_levels():
    weak, strong, few = (
        _info("Linkage", "6.1.2"),
        _info("Segregation", "6.1.1"),
        _info("Few", "6.1.3"),
    )
    tallies = {
        weak.id: service.Tally(correct=1, attempted=6),  # 16.7 %: F, reliable
        strong.id: service.Tally(correct=5, attempted=5),  # 100 %: A
        few.id: service.Tally(correct=0, attempted=2),  # 0 %, but only 2 answers
    }
    result = service.build_concept_insights(
        tallies, [strong, few, weak], total_answers=13, linked_answers=13
    )
    assert [c.name for c in result.concepts] == ["Few", "Linkage", "Segregation"]
    assert result.weak_concepts == ["Linkage"]  # "Few" has too few answers to be called weak
    assert result.insufficient_data_concepts == ["Few"]
    assert [c.grade for c in result.concepts] == ["F", "F", "A"]
    assert result.note != service.NO_LINKS_NOTE


def test_concept_insights_explain_when_questions_are_not_linked():
    result = service.build_concept_insights({}, [], total_answers=8, linked_answers=0)
    assert result.concepts == []
    assert (result.linked_answers, result.total_answers) == (0, 8)
    assert result.note == service.NO_LINKS_NOTE


def test_concept_insights_for_a_new_student():
    result = service.build_concept_insights({}, [], total_answers=0, linked_answers=0)
    assert result.concepts == [] and result.note != service.NO_LINKS_NOTE


async def test_concept_insights_require_login(anon_client):
    assert (await anon_client.get("/api/v1/insights/concepts")).status_code == 401


async def test_concept_insights_read_only_my_answers(client, monkeypatch):
    asked_for = []

    async def answers(session, user_id, attempt_id=None):
        asked_for.append(user_id)
        return []

    async def no_links(session, question_ids):
        return {}

    async def no_concepts(session, concept_ids):
        return []

    monkeypatch.setattr(repository, "get_mcq_answer_rows", answers)
    monkeypatch.setattr(repository, "get_concept_links", no_links)
    monkeypatch.setattr(repository, "get_concepts", no_concepts)
    response = await client.get("/api/v1/insights/concepts")
    assert response.status_code == 200, response.text
    assert asked_for == [STUDENT.id]
    assert response.json()["concepts"] == []


# --------------------------------------------------------------------------- full flow (DB)


@pytest.mark.db
async def test_after_attempt_marked_end_to_end(exam_data, db_session):  # noqa: F811
    """Generate + submit a paper, link two of its questions to a concept, then record."""
    async with _client(_app_with(FakeAIClient())) as c:
        paper = (
            await c.post(
                "/api/v1/papers/generate",
                json={"topic_ids": [str(exam_data.id)], "num_questions": 4},
            )
        ).json()
        q = paper["questions"]
        concept = Concept(topic_id=exam_data.id, name="Mastery test concept")
        db_session.add(concept)
        await db_session.flush()
        db_session.add_all(
            QuestionConcept(question_id=uuid.UUID(x["id"]), concept_id=concept.id) for x in q[:2]
        )
        await db_session.commit()

        answers = [{"question_id": q[0]["id"], "selected": "B"}]  # correct (concept)
        answers += [{"question_id": q[1]["id"], "selected": "A"}]  # wrong (concept)
        answers += [{"question_id": q[2]["id"], "selected": "A"}]  # wrong
        answers += [{"question_id": q[3]["id"], "selected": None}]  # unanswered
        submitted = await c.post(
            f"/api/v1/papers/{paper['paper_id']}/submit",
            json={"answers": answers, "explain": False},
        )
        assert submitted.status_code == 200, submitted.text
        attempt_id = uuid.UUID(submitted.json()["attempt_id"])

        async def count(model, *where):  # type: ignore[no-untyped-def]
            return await db_session.scalar(select(func.count()).select_from(model).where(*where))

        # ---- one call records everything
        recorded = await service.after_attempt_marked(
            db_session, STUDENT.id, attempt_id, source=MasterySource.EXAM
        )
        await db_session.commit()
        assert recorded == 2  # the two wrong answers
        assert await count(Mistake, Mistake.user_id == STUDENT.id) == 2

        snapshot = (
            await db_session.execute(
                select(UnitMastery).where(
                    UnitMastery.user_id == STUDENT.id, UnitMastery.source == "exam"
                )
            )
        ).scalar_one()
        assert snapshot.unit_id == exam_data.unit_id
        assert snapshot.mastery == 30  # 1 correct of 4 asked -> (1.5 / 5)

        mastery = (
            await db_session.execute(
                select(ConceptMastery).where(ConceptMastery.concept_id == concept.id)
            )
        ).scalar_one()
        assert (mastery.attempts_count, mastery.correct_count, mastery.mastery_score) == (2, 1, 0.5)

        # ---- calling again (or as a diagnostic) changes nothing
        again = await service.after_attempt_marked(
            db_session, STUDENT.id, attempt_id, source=MasterySource.DIAGNOSTIC
        )
        await db_session.commit()
        assert again == 0
        assert await count(UnitMastery, UnitMastery.user_id == STUDENT.id) == 1
        await db_session.refresh(mastery)
        assert (mastery.attempts_count, mastery.correct_count) == (2, 1)

        # ---- the endpoint
        body = (await c.get("/api/v1/insights/concepts")).json()
        assert (body["linked_answers"], body["total_answers"]) == (2, 3)
        [mine] = body["concepts"]
        assert (mine["name"], mine["correct"], mine["attempted"]) == ("Mastery test concept", 1, 2)
        assert (mine["percent"], mine["status"], mine["reliable"]) == (
            50.0,
            "insufficient_data",
            False,
        )
        assert body["insufficient_data_concepts"] == ["Mastery test concept"]
