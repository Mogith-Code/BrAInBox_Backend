"""Written-answer evaluation (evaluation module): typed and handwritten answers."""

import io

import pytest
from sqlalchemy import delete, select

from ai_service.errors import UserInputError
from ai_service.providers import set_providers
from ai_service.providers.fakes import FakeOCR
from ai_service.routes.jobs import DISPATCH
from api.core.errors import AppError
from api.modules.evaluation.service import accuracy_report, problems_from, reencode_image
from shared.db.models import (
    AnswerPoint,
    Concept,
    ConceptMastery,
    Evaluation,
    Keyword,
    Mistake,
    ModelAnswer,
    Question,
    QuestionConcept,
    Topic,
    Unit,
)
from shared.enums import ContentStatus, JobType, MistakeType, QuestionType
from tests.conftest import ADMIN, STUDENT, make_api_client


class PipelineAI:
    """Stands in for the ai_service: runs the real pipelines (with the fake providers) in
    this process, so the whole api -> job -> pipeline -> handler path is tested."""

    def __init__(self) -> None:
        self.jobs: list[str] = []

    async def run_job(self, job_id, job_type, payload):  # type: ignore[no-untyped-def]
        self.jobs.append(job_type)
        try:
            result = await DISPATCH[JobType(job_type)](payload)
        except UserInputError as exc:  # the real client turns the 422 into an AppError
            raise AppError(exc.message, code=exc.code, status_code=422) from exc
        return {"job_id": job_id, "job_type": job_type, "result": result}


# --------------------------------------------------------------------------- pure logic


def test_problems_put_required_and_valuable_points_first():
    points = [
        {"status": "covered", "text": "a", "marks": 1},
        {"status": "missing", "text": "small", "marks": 1, "problem": "missing_concept"},
        {"status": "partial", "text": "big", "marks": 3, "problem": "incomplete"},
        {"status": "missing", "text": "must", "marks": 1, "problem": "wrong_application",
         "is_required": True},
    ]  # fmt: skip
    problems = problems_from(points, {"in_order": False})
    assert problems[:3] == [
        (MistakeType.CONCEPTUAL, "must"),
        (MistakeType.INCOMPLETE, "big"),
        (MistakeType.KNOWLEDGE_GAP, "small"),
    ]
    assert problems[3][0] == MistakeType.INCOMPLETE and "structure" in problems[3][1]
    assert problems_from([{"status": "covered", "text": "a"}], {"in_order": True}) == []


def test_accuracy_report():
    assert accuracy_report([]).samples == 0
    report = accuracy_report([(4, 4), (3, 5), (2, 2.5)])
    assert report.samples == 3
    assert report.mean_absolute_error == 0.83
    assert report.within_one_mark == pytest.approx(0.667)
    assert report.correlation is not None and report.correlation > 0.5


def _png() -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (40, 30), "white").save(out, format="PNG")
    return out.getvalue()


def test_images_are_reencoded_as_jpeg():
    clean = reencode_image(_png())
    assert clean[:3] == b"\xff\xd8\xff"
    with pytest.raises(Exception):  # noqa: B017, PT011 - any decode error is fine
        reencode_image(b"not a picture")


async def test_evaluations_require_login(anon_client):
    assert (await anon_client.get("/api/v1/evaluations")).status_code == 401


async def test_admin_routes_need_the_admin_role(client):
    assert (await client.get("/api/v1/admin/evaluations/accuracy")).status_code == 403


# --------------------------------------------------------------------------- database fixtures

MODEL_ANSWER = (
    "Active transport moves substances against the concentration gradient. "
    "Energy from ATP is required. Carrier proteins in the membrane are used."
)


async def _wipe(session) -> None:  # type: ignore[no-untyped-def]
    """Remove unit 92 and everything the tests hang on it."""
    await session.rollback()
    await session.execute(delete(Mistake).where(Mistake.user_id == STUDENT.id))
    await session.execute(delete(Evaluation).where(Evaluation.user_id == STUDENT.id))
    topics = select(Topic.id).join(Unit, Unit.id == Topic.unit_id).where(Unit.number == 92)
    await session.execute(delete(Question).where(Question.topic_id.in_(topics)))
    await session.execute(delete(Unit).where(Unit.number == 92))
    await session.commit()


@pytest.fixture
async def written(db_session, student_in_db):
    """A structured question (4 marks) with an approved 3-point marking scheme, linked to a
    concept; plus one without a scheme."""
    await _wipe(db_session)  # leftovers of an earlier run that crashed
    unit = Unit(number=92, title="Evaluation unit")
    db_session.add(unit)
    await db_session.flush()
    topic = Topic(unit_id=unit.id, number="92.1", title="Membrane transport", code="bio-92.1")
    db_session.add(topic)
    await db_session.flush()
    concept = Concept(topic_id=topic.id, name="Active transport")
    db_session.add(concept)
    await db_session.flush()
    question = Question(
        topic_id=topic.id,
        question_type=QuestionType.STRUCTURED,
        stem="Describe active transport.",
        marks=4,
        status=ContentStatus.APPROVED,
    )
    bare = Question(
        topic_id=topic.id,
        question_type=QuestionType.ESSAY,
        stem="Discuss osmosis.",
        marks=10,
        status=ContentStatus.APPROVED,
    )
    db_session.add_all([question, bare])
    await db_session.flush()
    db_session.add(QuestionConcept(question_id=question.id, concept_id=concept.id))
    answer = ModelAnswer(
        question_id=question.id,
        answer_text=MODEL_ANSWER,
        total_marks=4,
        status=ContentStatus.APPROVED,
    )
    db_session.add(answer)
    await db_session.flush()
    specs = [
        ("Active transport moves substances against the concentration gradient", 2, "gradient"),
        ("Energy from ATP is required", 1, "ATP"),
        ("Carrier proteins in the membrane are used", 1, "carrier protein"),
    ]
    for n, (text, marks, keyword) in enumerate(specs):
        point = AnswerPoint(model_answer_id=answer.id, point_text=text, marks=marks, order_index=n)
        db_session.add(point)
        await db_session.flush()
        db_session.add(Keyword(answer_point_id=point.id, keyword=keyword))
    await db_session.commit()
    yield {"question": question.id, "bare": bare.id, "concept": concept.id}
    await _wipe(db_session)


# --------------------------------------------------------------------------- typed answers


@pytest.mark.db
async def test_only_questions_with_a_scheme_are_listed(written):
    async with make_api_client(user=STUDENT) as c:
        listed = (await c.get("/api/v1/evaluations/questions", params={"unit": "92"})).json()
        essays = (
            await c.get(
                "/api/v1/evaluations/questions", params={"unit": "92", "question_type": "essay"}
            )
        ).json()
    assert [q["stem"] for q in listed["items"]] == ["Describe active transport."]
    assert listed["items"][0]["my_attempts"] == 0 and listed["items"][0]["marks"] == 4
    assert essays["total"] == 0


@pytest.mark.db
async def test_typed_answer_is_marked_with_points_mistakes_and_mastery(written, db_session):
    ai = PipelineAI()
    answer = "Active transport moves substances against the concentration gradient."
    async with make_api_client(user=STUDENT, ai=ai) as c:
        started = await c.post(
            "/api/v1/evaluations",
            json={"question_id": str(written["question"]), "answer_text": answer},
        )
        assert started.status_code == 202, started.text
        ids = started.json()
        job = (await c.get(f"/api/v1/jobs/{ids['job_id']}")).json()
        result = (await c.get(f"/api/v1/evaluations/{ids['evaluation_id']}")).json()
        history = (await c.get("/api/v1/evaluations")).json()
        listed = (await c.get("/api/v1/evaluations/questions", params={"unit": "92"})).json()
    assert ai.jobs == ["evaluate_answer"]
    assert job["status"] == "succeeded"
    assert result["status"] == "succeeded" and result["source"] == "typed"
    assert (result["estimated_marks"], result["max_marks"], result["percent"]) == (2, 4, 50)
    assert (result["covered"], result["partial"], result["missing"]) == (1, 0, 2)
    assert [p["status"] for p in result["points"]] == ["covered", "missing", "missing"]
    assert result["points"][0]["matched_keywords"] == ["gradient"]
    assert result["model_answer"] == MODEL_ANSWER
    assert len(result["tips"]) == 2
    assert result["disclaimer"].startswith("Formative feedback")
    assert history["items"][0]["estimated_marks"] == 2
    assert listed["items"][0]["my_attempts"] == 1 and listed["items"][0]["my_best_marks"] == 2

    mistakes = (
        (await db_session.execute(select(Mistake).where(Mistake.user_id == STUDENT.id)))
        .scalars()
        .all()
    )
    assert len(mistakes) == 2
    assert {m.mistake_type for m in mistakes} == {MistakeType.KNOWLEDGE_GAP}
    assert all(m.concept_id == written["concept"] and m.response_id is None for m in mistakes)
    mastery = (
        await db_session.execute(
            select(ConceptMastery.mastery_score).where(ConceptMastery.user_id == STUDENT.id)
        )
    ).scalar_one()
    assert mastery == pytest.approx(0.5)  # 0.7 * 0.5 + 0.3 * (2 / 4)


@pytest.mark.db
async def test_errors(written):
    ai = PipelineAI()
    async with make_api_client(user=STUDENT, ai=ai) as c:
        no_scheme = await c.post(
            "/api/v1/evaluations", json={"question_id": str(written["bare"]), "answer_text": "x"}
        )
        unknown = await c.post(
            "/api/v1/evaluations",
            json={"question_id": "00000000-0000-0000-0000-00000000dead", "answer_text": "x"},
        )
        too_short = await c.post(
            "/api/v1/evaluations",
            json={"question_id": str(written["question"]), "answer_text": "a"},
        )
        failed = (await c.get(f"/api/v1/evaluations/{too_short.json()['evaluation_id']}")).json()
        other = await c.get("/api/v1/evaluations/00000000-0000-0000-0000-00000000dead")
    assert no_scheme.json()["error"]["code"] == "NO_MARKING_SCHEME"
    assert unknown.json()["error"]["code"] == "QUESTION_NOT_FOUND"
    assert failed["status"] == "failed" and failed["error"].startswith("Write your answer")
    assert failed["model_answer"] is None  # never shown before the answer is marked
    assert other.json()["error"]["code"] == "EVALUATION_NOT_FOUND"


@pytest.mark.db
async def test_daily_limit(written, monkeypatch):
    from api.core.config import get_settings

    monkeypatch.setattr(get_settings(), "EVALUATIONS_DAILY_LIMIT", 1)
    body = {"question_id": str(written["question"]), "answer_text": "Energy from ATP is required."}
    async with make_api_client(user=STUDENT, ai=PipelineAI()) as c:
        first = await c.post("/api/v1/evaluations", json=body)
        second = await c.post("/api/v1/evaluations", json=body)
    assert first.status_code == 202
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "DAILY_LIMIT_REACHED"


# --------------------------------------------------------------------------- handwritten answers


class ReadsModelAnswer(FakeOCR):
    async def extract_text(self, image_bytes: bytes) -> str:
        return MODEL_ANSWER


@pytest.mark.db
async def test_handwritten_flow_ocr_then_evaluate(written, monkeypatch, tmp_path):
    from ai_service.providers.storage import LocalStorage
    from api.core.config import get_settings

    # The api writes the photos to the local storage folder; the ai_service reads them there.
    monkeypatch.setattr(get_settings(), "LOCAL_STORAGE_DIR", str(tmp_path))
    set_providers(ocr=ReadsModelAnswer(), storage=LocalStorage(str(tmp_path)))
    ai = PipelineAI()
    async with make_api_client(user=STUDENT, ai=ai) as c:
        pages = await c.post(
            "/api/v1/evaluations/pages",
            files=[
                ("files", ("p1.png", _png(), "image/png")),
                ("files", ("p2.png", _png(), "image/png")),
            ],
        )
        assert pages.status_code == 201, pages.text
        paths = pages.json()["image_paths"]
        not_mine = await c.post(
            "/api/v1/evaluations/ocr",
            json={
                "question_id": str(written["question"]),
                "image_paths": ["answers/other/x/page-1.jpg"],
            },
        )
        ocr = await c.post(
            "/api/v1/evaluations/ocr",
            json={"question_id": str(written["question"]), "image_paths": paths},
        )
        assert ocr.status_code == 202, ocr.text
        evaluation_id = ocr.json()["evaluation_id"]
        preview = (await c.get(f"/api/v1/evaluations/{evaluation_id}")).json()
        marked = await c.post(
            "/api/v1/evaluations",
            json={
                "question_id": str(written["question"]),
                "answer_text": preview["ocr_text"],
                "evaluation_id": evaluation_id,
            },
        )
        result = (await c.get(f"/api/v1/evaluations/{evaluation_id}")).json()
        again = await c.post(
            "/api/v1/evaluations",
            json={
                "question_id": str(written["question"]),
                "answer_text": "changed",
                "evaluation_id": evaluation_id,
            },
        )
        bad_file = await c.post(
            "/api/v1/evaluations/pages", files=[("files", ("a.pdf", b"%PDF", "application/pdf"))]
        )
    assert pages.json()["pages"] == 2
    assert paths[0].startswith(f"answers/{STUDENT.id}/") and paths[0].endswith("/page-1.jpg")
    assert not_mine.json()["error"]["code"] == "INVALID_IMAGE_PATH"
    assert preview["status"] == "ocr_ready" and preview["source"] == "handwritten"
    assert preview["ocr_text"].count("Energy from ATP") == 2  # two pages were read
    assert preview["estimated_marks"] is None and preview["model_answer"] is None
    assert marked.status_code == 202
    assert ai.jobs == ["ocr_answer", "evaluate_answer"]
    assert result["status"] == "succeeded" and result["estimated_marks"] == 4
    assert result["missing"] == 0 and result["tips"] == []
    assert again.json()["error"]["code"] == "ALREADY_EVALUATED"
    assert bad_file.json()["error"]["code"] == "UNSUPPORTED_IMAGE"


# --------------------------------------------------------------------------- admin accuracy


@pytest.mark.db
async def test_manual_marks_feed_the_accuracy_report(written, admin_in_db):
    body = {"question_id": str(written["question"]), "answer_text": MODEL_ANSWER}
    async with make_api_client(user=STUDENT, ai=PipelineAI()) as c:
        evaluation_id = (await c.post("/api/v1/evaluations", json=body)).json()["evaluation_id"]
    async with make_api_client(user=ADMIN) as c:
        too_high = await c.patch(
            f"/api/v1/admin/evaluations/{evaluation_id}", json={"manual_marks": 9}
        )
        saved = await c.patch(
            f"/api/v1/admin/evaluations/{evaluation_id}", json={"manual_marks": 3}
        )
        report = (await c.get("/api/v1/admin/evaluations/accuracy")).json()
        listed = (await c.get("/api/v1/admin/evaluations", params={"only_manual": True})).json()
    assert too_high.json()["error"]["code"] == "MARKS_TOO_HIGH"
    assert saved.json()["difference"] == 1
    assert report["samples"] >= 1 and report["mean_absolute_error"] is not None
    assert any(item["id"] == evaluation_id for item in listed["items"])
