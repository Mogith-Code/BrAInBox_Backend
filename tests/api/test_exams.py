"""Tests for the exams module: past papers, model paper blueprints, generation, marking
(MCQs at once, written answers through the evaluation module) and the daily limit.
Owner: Udith."""

import random
import uuid

import pytest
from sqlalchemy import delete, select

from api.core.ai_client import get_ai_client
from api.core.config import get_settings
from api.core.errors import ServiceUnavailableError, TooManyRequestsError
from api.core.security import get_current_user
from api.main import create_app
from api.modules.exams import service as exams_service
from api.modules.exams.schemas import DifficultyMix, PaperBlueprint
from api.modules.exams.service import (
    GradingQuestion,
    Target,
    evaluate_paper,
    option_from_letter,
    plan_gaps,
    split_by_mix,
)
from api.modules.knowledge_base import service as knowledge_service
from shared.db.models import (
    AIJob,
    AnswerPoint,
    Attempt,
    MCQOption,
    ModelAnswer,
    Paper,
    PaperQuestion,
    Question,
    Response,
    Topic,
    Unit,
    User,
)
from shared.enums import ContentStatus, Difficulty, JobType, QuestionType, UserRole
from tests.conftest import ADMIN, STUDENT, _client

# --------------------------------------------------------------------------- marking (no DB)

OPTIONS = ["Ribosome", "Mitochondrion", "Golgi apparatus", "Lysosome", "Nucleus"]


def make_question(topic: str = "Cells", correct: str = "Mitochondrion", marks: int = 1):
    return GradingQuestion(uuid.uuid4(), topic, "Where is ATP made?", OPTIONS, correct, marks)


def test_option_from_letter():
    q = make_question()
    assert option_from_letter(q, "B") == "Mitochondrion"
    assert option_from_letter(q, " b ") == "Mitochondrion"
    assert option_from_letter(q, "Z") is None
    assert option_from_letter(q, "") is None
    assert option_from_letter(q, None) is None


def test_evaluate_paper_scores_topics_and_weak_topics():
    cells = [make_question("Cells"), make_question("Cells", marks=2)]
    plants = [make_question("Photosynthesis"), make_question("Photosynthesis")]
    chosen = {
        cells[0].id: "B",  # correct
        cells[1].id: "B",  # correct, 2 marks
        plants[0].id: "A",  # wrong
        # plants[1] not answered
    }
    result = evaluate_paper(uuid.uuid4(), cells + plants, chosen)

    assert (result.total_questions, result.answered, result.correct) == (4, 3, 2)
    assert (result.marks_obtained, result.marks_total, result.percent) == (3, 5, 60.0)
    assert {t.topic: t.percent for t in result.by_topic} == {"Cells": 100.0, "Photosynthesis": 0.0}
    assert result.weak_topics == ["Photosynthesis"]
    assert result.results[2].selected_option == "Ribosome"
    assert result.results[3].selected_option is None
    assert result.results[3].marks_awarded == 0


def test_evaluate_empty_paper():
    result = evaluate_paper(uuid.uuid4(), [], {})
    assert result.percent == 0.0
    assert result.weak_topics == []


async def test_generate_needs_at_least_one_topic(client):
    response = await client.post("/api/v1/papers/generate", json={"topic_ids": []})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_generate_by_units_validation(client):
    # Empty unit list
    res = await client.post("/api/v1/papers/generate-by-units", json={"unit_numbers": []})
    assert res.status_code == 422

    # Invalid unit number
    res = await client.post("/api/v1/papers/generate-by-units", json={"unit_numbers": [0, 11]})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "INVALID_UNITS"


# --------------------------------------------------------------------------- blueprint (no DB)


def test_split_by_mix():
    assert split_by_mix(10, DifficultyMix()) == {
        Difficulty.EASY: 3,
        Difficulty.MEDIUM: 5,
        Difficulty.HARD: 2,
    }
    assert split_by_mix(1, DifficultyMix()) == {
        Difficulty.EASY: 0,
        Difficulty.MEDIUM: 1,
        Difficulty.HARD: 0,
    }
    only_easy = split_by_mix(3, DifficultyMix(easy=1, medium=0, hard=0))
    assert only_easy[Difficulty.EASY] == 3 and sum(only_easy.values()) == 3
    assert sum(split_by_mix(7, DifficultyMix(easy=1, medium=1, hard=1)).values()) == 7


def test_plan_gaps_spreads_over_targets():
    a, b = Target("Cells", uuid.uuid4()), Target("Genetics", uuid.uuid4(), uuid.uuid4())
    gaps = plan_gaps(
        {(QuestionType.MCQ, Difficulty.EASY): 3, (QuestionType.ESSAY, Difficulty.HARD): 1},
        [a, b],
    )
    assert [(g["question_type"], g["title"], g["count"]) for g in gaps] == [
        ("mcq", "Cells", 2),
        ("mcq", "Genetics", 1),
        ("essay", "Genetics", 1),  # the extra question moves on to the next target
    ]
    assert gaps[2]["topic_id"] == str(b.topic_id) and gaps[0]["topic_id"] is None
    assert plan_gaps({(QuestionType.MCQ, Difficulty.EASY): 2}, []) == []


def test_old_generate_body_still_means_mcqs():
    topic = uuid.uuid4()
    old = PaperBlueprint.model_validate({"topic_ids": [str(topic)], "num_questions": 7})
    assert (old.mcq_count, old.structured_count, old.essay_count) == (7, 0, 0)
    assert PaperBlueprint.model_validate({"unit_numbers": [2]}).mcq_count == 20
    mixed = PaperBlueprint.model_validate({"unit_numbers": [2], "essay_count": 1})
    assert (mixed.mcq_count, mixed.essay_count) == (0, 1)


async def test_generate_validation(client):
    bad = [
        {"unit_numbers": [2], "difficulty": {"easy": 0, "medium": 0, "hard": 0}},
        {"unit_numbers": [2], "essay_count": 7},
        {"unit_numbers": [2], "time_limit_minutes": 5},
    ]
    for body in bad:
        response = await client.post("/api/v1/papers/generate", json=body)
        assert response.status_code == 422, body


async def test_daily_limit(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "PAPERS_DAILY_LIMIT", 2)
    used = {"n": 2}

    async def count(session, user_id, job_type, since):  # type: ignore[no-untyped-def]
        assert job_type == JobType.BUILD_PAPER
        return used["n"]

    monkeypatch.setattr(exams_service.jobs_service, "count_recent_jobs", count)
    with pytest.raises(TooManyRequestsError) as err:
        await exams_service.check_papers_limit(None, STUDENT)  # type: ignore[arg-type]
    assert err.value.code == "DAILY_LIMIT_REACHED"
    await exams_service.check_papers_limit(None, ADMIN)  # type: ignore[arg-type]  # admins: none
    used["n"] = 1
    await exams_service.check_papers_limit(None, STUDENT)  # type: ignore[arg-type]
    monkeypatch.setattr(settings, "PAPERS_DAILY_LIMIT", 0)  # 0 = no limit
    used["n"] = 99
    await exams_service.check_papers_limit(None, STUDENT)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "params", [{"year": 1800}, {"type": "poem"}, {"page": 0}], ids=["year", "type", "page"]
)
async def test_list_papers_validation(client, params):
    assert (await client.get("/api/v1/papers", params=params)).status_code == 422


async def test_papers_need_login(anon_client):
    assert (await anon_client.get("/api/v1/papers")).status_code == 401
    assert (await anon_client.get(f"/api/v1/papers/{uuid.uuid4()}")).status_code == 401


# --------------------------------------------------------------------------- full flow (DB)


class FakeAIClient:
    """Stands in for the ai_service: BUILD_PAPER returns fixed questions (topic / unit papers)
    or fills the blueprint gaps; EVALUATE_ANSWER gives 3 marks; explanations echo."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[str] = []
        self.payloads: list[dict] = []
        self.counter = 0

    def _gap_question(self, gap: dict) -> dict:
        self.counter += 1
        base = {
            "question_type": gap["question_type"],
            "difficulty": gap["difficulty"],
            "topic_id": gap.get("topic_id"),
            "unit_id": gap.get("unit_id"),
            "prompt_version": "test.v1",
        }
        if gap["question_type"] == "mcq":
            return {**base, "question": f"Generated MCQ {self.counter}?", "options": OPTIONS,
                    "correct_answer": "Mitochondrion", "explanation": "", "marks": 1}  # fmt: skip
        marks = 10 if gap["question_type"] == "essay" else 4
        points = [{"text": f"Point {i}", "marks": 2, "keywords": ["ATP", "atp"]}
                  for i in range(marks // 2)]  # fmt: skip
        return {**base, "question": f"Generated {gap['question_type']} {self.counter}.",
                "marks": marks, "model_answer": "A full answer.", "points": points}  # fmt: skip

    async def run_job(self, job_id, job_type, payload):  # type: ignore[no-untyped-def]
        self.calls.append(job_type)
        self.payloads.append(payload)
        if self.fail:
            raise ServiceUnavailableError("ai_service down", code="AI_SERVICE_UNAVAILABLE")
        if job_type == "evaluate_answer":
            result = {"estimated_marks": 3, "max_marks": payload["max_marks"], "points": [],
                      "feedback": "Good start.", "prompt_version": "test.v1"}  # fmt: skip
            return {"job_id": job_id, "job_type": job_type, "result": result}
        if payload.get("gaps") is not None:
            questions = [self._gap_question(g) for g in payload["gaps"] for _ in range(g["count"])]
            result = {"questions": questions, "warnings": [], "prompt_version": "test.v1"}
            return {"job_id": job_id, "job_type": job_type, "result": result}
        items = payload.get("topics") or payload.get("units") or []
        questions = [
            {
                "question": f"Question {i} about {item['title']}?",
                "options": OPTIONS,
                "correct_answer": "Mitochondrion",  # = letter B
                "explanation": "",
                "marks": 1,
                "topic_id": item.get("topic_id"),
                "unit_id": item.get("unit_id"),  # set for unit papers
            }
            for item in items
            for i in range(payload["num_questions"])
        ]
        result = {"questions": questions, "warnings": [], "prompt_version": "test.v1"}
        return {"job_id": job_id, "job_type": job_type, "result": result}

    async def sync(self, name, payload):  # type: ignore[no-untyped-def]
        self.calls.append(name)
        explanations = {i["question_id"]: "Because ATP is made there." for i in payload["items"]}
        return {"name": name, "status": "ok", "result": {"explanations": explanations}}


@pytest.fixture
async def exam_data(db_session):
    """A student user + one unit/topic in the database; everything is removed afterwards."""
    user = await db_session.get(User, STUDENT.id)
    if user is None:
        user = User(id=STUDENT.id, firebase_uid=STUDENT.firebase_uid, role=UserRole.STUDENT)
        db_session.add(user)
    unit = Unit(number=random.randint(1000, 999_999), title="Test unit")
    db_session.add(unit)
    await db_session.flush()
    topic = Topic(unit_id=unit.id, number="T.1", title="Test topic")
    db_session.add(topic)
    await db_session.commit()
    topic_id, unit_id = topic.id, unit.id  # a rollback expires the rows (MissingGreenlet)
    yield topic
    await db_session.rollback()
    for stmt in (
        delete(Paper).where(Paper.title.like(f"{TAG}%")),
        delete(Question).where(Question.created_by == STUDENT.id),
        delete(Question).where(Question.topic_id == topic_id),
        delete(Paper).where(Paper.created_by == STUDENT.id),
        delete(AIJob).where(AIJob.requested_by == STUDENT.id),
        delete(User).where(User.id == STUDENT.id),
        delete(Unit).where(Unit.id == unit_id),
    ):
        await db_session.execute(stmt)
    await db_session.commit()


def _app_with(ai: FakeAIClient):  # type: ignore[no-untyped-def]
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: STUDENT
    app.dependency_overrides[get_ai_client] = lambda: ai
    return app


TAG = "ExamTest"


async def _bank_question(  # type: ignore[no-untyped-def]
    db_session, topic, kind=QuestionType.MCQ, difficulty=Difficulty.MEDIUM, **extra
) -> Question:
    """An approved bank question; MCQs get options (B right), written ones a marking scheme
    unless scheme=False."""
    scheme = extra.pop("scheme", True)
    q = Question(topic_id=topic.id, unit_id=topic.unit_id, question_type=kind,
                 difficulty=difficulty, stem=extra.pop("stem", f"{TAG} {uuid.uuid4().hex[:6]}"),
                 marks=extra.pop("marks", 1 if kind == QuestionType.MCQ else 4),
                 source="admin", status=ContentStatus.APPROVED, **extra)  # fmt: skip
    db_session.add(q)
    await db_session.flush()
    if kind == QuestionType.MCQ:
        db_session.add_all(
            MCQOption(question_id=q.id, label=label, text=text, is_correct=text == OPTIONS[1])
            for label, text in zip("ABCDE", OPTIONS, strict=True)
        )
    elif scheme:
        answer = ModelAnswer(question_id=q.id, answer_text="Model.", total_marks=q.marks,
                             source="admin", status=ContentStatus.APPROVED)  # fmt: skip
        db_session.add(answer)
        await db_session.flush()
        db_session.add(AnswerPoint(model_answer_id=answer.id, point_text="ATP", marks=q.marks))
    await db_session.commit()
    return q


async def _job(c, job_id: str) -> dict:  # type: ignore[no-untyped-def]
    response = await c.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200, response.text
    return response.json()


async def generate_paper(c, body: dict) -> dict:  # type: ignore[no-untyped-def]
    """POST /papers/generate is a queued job now (202 + job id).
    Wait for the job, then return the paper from GET /papers/{id}.
    "paper_id" is added so older tests can keep using it."""
    queued = await c.post("/api/v1/papers/generate", json=body)
    assert queued.status_code == 202, queued.text
    job = await _job(c, queued.json()["job_id"])
    assert job["status"] == "succeeded", job
    paper = (await c.get(f"/api/v1/papers/{job['result']['paper_id']}")).json()
    paper["paper_id"] = paper["id"]
    return paper


@pytest.mark.db
async def test_blueprint_uses_unseen_bank_questions_and_generates_the_gaps(exam_data, db_session):
    topic = exam_data
    unseen = await _bank_question(db_session, topic)
    seen = await _bank_question(db_session, topic)
    structured = await _bank_question(db_session, topic, QuestionType.STRUCTURED)
    await _bank_question(db_session, topic, QuestionType.STRUCTURED, scheme=False)  # unmarkable
    await _bank_question(db_session, topic, difficulty=Difficulty.HARD)  # wrong difficulty
    await _bank_question(db_session, topic, is_outdated=True)  # outdated
    # The student already answered `seen` in a quiz.
    quiz = Paper(title=f"{TAG} quiz", paper_type="quiz")
    db_session.add(quiz)
    await db_session.flush()
    attempt = Attempt(paper_id=quiz.id, user_id=STUDENT.id)
    db_session.add(attempt)
    await db_session.flush()
    db_session.add(Response(attempt_id=attempt.id, question_id=seen.id, is_correct=True))
    await db_session.commit()

    ai = FakeAIClient()
    blueprint = {
        "topic_ids": [str(topic.id)],
        "mcq_count": 2,
        "structured_count": 1,
        "essay_count": 1,
        "difficulty": {"easy": 0, "medium": 1, "hard": 0},
        "time_limit_minutes": 90,
        "title": f"{TAG} blueprint",
    }
    async with _client(_app_with(ai)) as c:
        queued = await c.post("/api/v1/papers/generate", json=blueprint)
        assert queued.status_code == 202, queued.text
        assert (queued.json()["from_bank"], queued.json()["to_generate"]) == (2, 2)
        job = await _job(c, queued.json()["job_id"])
        assert job["status"] == "succeeded", job
        assert (job["result"]["from_bank"], job["result"]["generated"]) == (2, 2)
        paper = (await c.get(f"/api/v1/papers/{job['result']['paper_id']}")).json()

    [payload] = ai.payloads
    assert [(g["question_type"], g["difficulty"], g["count"]) for g in payload["gaps"]] == [
        ("mcq", "medium", 1),
        ("essay", "medium", 1),
    ]
    assert payload["gaps"][0]["topic_id"] == str(topic.id)
    assert unseen.stem in payload["existing"]  # for the AI's duplicate check

    assert (paper["title"], paper["duration_minutes"], paper["paper_type"]) == (
        f"{TAG} blueprint",
        90,
        "ai_generated",
    )
    types = [q["question_type"] for q in paper["questions"]]
    assert types == ["mcq", "mcq", "structured", "essay"]  # MCQs first, like the real paper
    ids = {q["id"] for q in paper["questions"]}
    assert str(unseen.id) in ids and str(structured.id) in ids and str(seen.id) not in ids
    assert paper["total_marks"] == 1 + 1 + 4 + 10
    assert "correct_answer" not in str(paper) and "is_correct" not in str(paper)

    essay_id = uuid.UUID(paper["questions"][3]["id"])
    essay = await db_session.get(Question, essay_id)
    assert (essay.source, essay.status) == ("ai", ContentStatus.PENDING_REVIEW)
    assert await knowledge_service.get_marking_scheme(db_session, essay_id) is None
    scheme = await knowledge_service.get_marking_scheme(db_session, essay_id, allow_ai_draft=True)
    assert scheme is not None and scheme.total_marks == 10 and len(scheme.points) == 5
    assert [k["keyword"] for k in scheme.points[0].keywords] == ["ATP"]  # "atp" de-duplicated


@pytest.mark.db
async def test_generate_with_unknown_topic(exam_data):
    async with _client(_app_with(FakeAIClient())) as c:
        response = await c.post("/api/v1/papers/generate", json={"topic_ids": [str(uuid.uuid4())]})
        units = await c.post("/api/v1/papers/generate", json={"unit_numbers": [987_654]})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TOPIC_NOT_FOUND"
    assert units.json()["error"]["code"] == "UNIT_NOT_FOUND"


@pytest.mark.db
async def test_generate_when_ai_service_fails(exam_data, db_session):
    async with _client(_app_with(FakeAIClient(fail=True))) as c:
        queued = await c.post("/api/v1/papers/generate", json={"topic_ids": [str(exam_data.id)]})
        assert queued.status_code == 202, queued.text
        job = await _job(c, queued.json()["job_id"])
    assert job["status"] == "failed" and job["error_code"] == "AI_SERVICE_UNAVAILABLE"
    papers = (await db_session.execute(select(Paper).where(Paper.created_by == STUDENT.id))).all()
    assert papers == []


@pytest.mark.db
async def test_papers_daily_limit(exam_data, monkeypatch):
    monkeypatch.setattr(get_settings(), "PAPERS_DAILY_LIMIT", 1)
    async with _client(_app_with(FakeAIClient())) as c:
        body = {"topic_ids": [str(exam_data.id)], "num_questions": 1}
        first = await c.post("/api/v1/papers/generate", json=body)
        second = await c.post("/api/v1/papers/generate", json=body)
        old_url = await c.post("/exam/generate-paper", json=body)
    assert first.status_code == 202
    assert (second.status_code, second.json()["error"]["code"]) == (429, "DAILY_LIMIT_REACHED")
    assert old_url.status_code == 429  # every way of generating counts


@pytest.mark.db
async def test_submit_with_written_answers(exam_data, db_session):
    """MCQs are marked at once; written answers by the evaluation module, then the attempt is
    graded with the full score."""
    topic = exam_data
    mcq = await _bank_question(db_session, topic)
    structured = await _bank_question(db_session, topic, QuestionType.STRUCTURED, marks=4)
    blank = await _bank_question(db_session, topic, QuestionType.STRUCTURED)
    no_scheme = await _bank_question(db_session, topic, QuestionType.ESSAY, scheme=False, marks=10)
    paper = Paper(title=f"{TAG} mine", paper_type="ai_generated", created_by=STUDENT.id)
    db_session.add(paper)
    await db_session.flush()
    db_session.add_all(
        PaperQuestion(paper_id=paper.id, question_id=q.id, position=n, marks=q.marks)
        for n, q in enumerate([mcq, structured, blank, no_scheme], start=1)
    )
    await db_session.commit()

    ai = FakeAIClient()
    async with _client(_app_with(ai)) as c:
        response = await c.post(
            f"/api/v1/papers/{paper.id}/submit",
            json={
                "answers": [
                    {"question_id": str(mcq.id), "selected": "B"},
                    {"question_id": str(structured.id), "answer_text": "ATP is made..."},
                    {"question_id": str(blank.id), "answer_text": "   "},
                    {"question_id": str(no_scheme.id), "answer_text": "An essay."},
                ],
                "explain": False,
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()
        written = {w["question_id"]: w for w in result["written"]}
        evaluation = await c.get(
            f"/api/v1/evaluations/{written[str(structured.id)]['evaluation_id']}"
        )

    assert (result["marks_obtained"], result["correct"], result["total_questions"]) == (1, 1, 4)
    assert (result["status"], result["pending_written"], result["answered"]) == ("marking", 1, 3)
    assert result["written_marks_total"] == 4 + 4 + 10
    assert written[str(structured.id)]["status"] == "queued"
    assert written[str(blank.id)]["status"] == "unanswered"
    assert written[str(no_scheme.id)]["status"] == "not_markable"
    assert ai.calls == ["evaluate_answer"]  # the job ran in the background (after the response)
    assert evaluation.json()["status"] == "succeeded"
    assert evaluation.json()["estimated_marks"] == 3

    attempt = await db_session.get(Attempt, uuid.UUID(result["attempt_id"]))
    await db_session.refresh(attempt)
    assert (attempt.status, attempt.score) == ("graded", 1 + 3)
    answers = {
        r.question_id: r
        for r in (
            await db_session.execute(select(Response).where(Response.attempt_id == attempt.id))
        ).scalars()
    }
    assert answers[structured.id].marks_awarded == 3
    assert answers[structured.id].answer_text == "ATP is made..."
    assert answers[blank.id].marks_awarded == 0


@pytest.mark.db
async def test_list_and_view_past_papers(exam_data, db_session):
    topic = exam_data
    year = random.randint(1990, 2100)
    fresh = await _bank_question(db_session, topic)
    old = await _bank_question(db_session, topic, is_outdated=True)
    essay = await _bank_question(db_session, topic, QuestionType.ESSAY)
    listed_paper = Paper(title=f"{TAG} {year} I", paper_type="past_paper", year=year,
                         status=ContentStatus.APPROVED, duration_minutes=120)  # fmt: skip
    draft = Paper(title=f"{TAG} {year} draft", paper_type="past_paper", year=year)
    theirs = Paper(title=f"{TAG} theirs", paper_type="ai_generated")
    db_session.add_all([listed_paper, draft, theirs])
    await db_session.flush()
    db_session.add_all(
        PaperQuestion(paper_id=p.id, question_id=q.id, position=n, marks=q.marks)
        for p in (listed_paper, draft, theirs)
        for n, q in enumerate([fresh, old, essay], start=1)
    )
    await db_session.commit()

    async with _client(_app_with(FakeAIClient())) as c:
        by_year = (await c.get("/api/v1/papers", params={"year": year})).json()
        essays = (await c.get("/api/v1/papers", params={"year": year, "type": "essay"})).json()
        structured = await c.get("/api/v1/papers", params={"year": year, "type": "structured"})
        detail = (await c.get(f"/api/v1/papers/{listed_paper.id}")).json()
        hidden = (await c.get(f"/api/v1/papers/{listed_paper.id}?hide_outdated=true")).json()
        other = await c.get(f"/api/v1/papers/{theirs.id}")
        unapproved = await c.get(f"/api/v1/papers/{draft.id}")

    [row] = by_year["items"]  # the draft is not listed
    assert (row["id"], row["question_count"], row["outdated_count"]) == (str(listed_paper.id), 3, 1)
    assert (row["question_types"], row["duration_minutes"]) == (["essay", "mcq"], 120)
    assert [p["id"] for p in essays["items"]] == [str(listed_paper.id)]
    assert structured.json()["items"] == []

    assert [q["is_outdated"] for q in detail["questions"]] == [False, True, False]
    assert detail["questions"][0]["options"][1] == {"label": "B", "text": "Mitochondrion"}
    assert detail["questions"][2]["options"] == []
    assert (hidden["question_count"], hidden["hidden_outdated"]) == (3, 1)
    assert [q["id"] for q in hidden["questions"]] == [str(fresh.id), str(essay.id)]
    assert other.json()["error"]["code"] == "PAPER_NOT_FOUND"
    assert unapproved.status_code == 404


@pytest.mark.db
async def test_submit_unknown_paper(exam_data):
    async with _client(_app_with(FakeAIClient())) as c:
        response = await c.post(f"/api/v1/papers/{uuid.uuid4()}/submit", json={"answers": []})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PAPER_NOT_FOUND"


# --------------------------------------------------------------------------- unit papers (DB)


@pytest.fixture
async def free_unit(db_session):  # type: ignore[no-untyped-def]
    """A unit with an unused number 1-10 (unit papers only accept 1-10), removed afterwards."""
    from sqlalchemy import select

    used = set((await db_session.execute(select(Unit.number))).scalars())
    free = [n for n in range(1, 11) if n not in used]
    if not free:
        pytest.skip("units 1-10 already exist in the test database")
    if await db_session.get(User, STUDENT.id) is None:
        db_session.add(
            User(id=STUDENT.id, firebase_uid=STUDENT.firebase_uid, role=UserRole.STUDENT)
        )
    unit = Unit(number=free[0], title="Genetics")
    db_session.add(unit)
    await db_session.commit()
    yield unit
    for stmt in (
        delete(Question).where(Question.created_by == STUDENT.id),
        delete(Paper).where(Paper.created_by == STUDENT.id),
        delete(AIJob).where(AIJob.requested_by == STUDENT.id),
        delete(User).where(User.id == STUDENT.id),
        delete(Unit).where(Unit.id == unit.id),
    ):
        await db_session.execute(stmt)
    await db_session.commit()


@pytest.mark.db
async def test_unit_paper_labels_questions_with_their_unit(free_unit, db_session):
    async with _client(_app_with(FakeAIClient())) as c:
        response = await c.post(
            "/api/v1/papers/generate-by-units",
            json={"units": [free_unit.number], "num_questions": 2},
        )
    assert response.status_code == 200, response.text
    paper = response.json()
    assert paper["title"] == f"Model paper: Units {free_unit.number}"
    assert [q["topic"] for q in paper["questions"]] == [f"Unit {free_unit.number}: Genetics"] * 2
    saved = await db_session.get(Question, uuid.UUID(paper["questions"][0]["id"]))
    assert saved is not None and saved.unit_id == free_unit.id  # the unit is saved too


# --------------------------------------------------------------------------- old /exam/* URLs


@pytest.mark.parametrize(
    "path", ["/exam/generate-paper", "/exam/generate-paper-by-units", "/exam/evaluate"]
)
async def test_old_exam_urls_need_login(anon_client, path):  # type: ignore[no-untyped-def]
    response = await anon_client.post(path, json={})
    assert response.status_code == 401


async def test_old_exam_urls_are_hidden_from_docs(client):  # type: ignore[no-untyped-def]
    paths = (await client.get("/openapi.json")).json()["paths"]
    assert not any(p.startswith("/exam/") for p in paths)


async def test_old_evaluate_rejects_a_bad_question_id(client):  # type: ignore[no-untyped-def]
    body = {"paper_id": str(uuid.uuid4()), "answers": [{"question_id": "nope", "selected": "A"}]}
    response = await client.post("/exam/evaluate", json=body)
    assert response.status_code == 422  # a clear validation error, not a server crash


@pytest.mark.db
async def test_old_exam_urls_work_like_the_new_ones(exam_data):  # type: ignore[no-untyped-def]
    async with _client(_app_with(FakeAIClient())) as c:
        generated = await c.post(
            "/exam/generate-paper", json={"topic_ids": [str(exam_data.id)], "num_questions": 2}
        )
        assert generated.status_code == 200, generated.text
        paper = generated.json()
        q1, q2 = paper["questions"]
        evaluated = await c.post(
            "/exam/evaluate",
            json={
                "paper_id": paper["paper_id"],
                "answers": [
                    {"question_id": q1["id"], "selected": "B"},
                    {"question_id": q2["id"], "selected": "A"},
                ],
                "explain": False,
            },
        )
    assert evaluated.status_code == 200, evaluated.text
    assert evaluated.json()["correct"] == 1
