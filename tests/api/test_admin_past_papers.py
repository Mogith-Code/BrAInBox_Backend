"""Admin past papers: upload -> background extraction -> questions -> model answers. Owner: Udith.

OCR is mocked: `past_paper_extract.read_pages` returns fixed page text, and the ai_service is
replaced by a client that runs the real pipeline in this process.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import delete

from ai_service.errors import UserInputError
from ai_service.pipelines.questions import past_paper_extract
from ai_service.pipelines.questions.past_paper_extract import readability, split_questions
from api.core import storage
from api.core.errors import AppError
from api.modules.questions import service as questions_service
from shared.db.models import AIJob, PastPaper
from tests.conftest import ADMIN, make_api_client

URL = "/api/v1/admin/questions/past-papers"
PDF = b"%PDF-1.4 fake paper"
PAPER_2_TEXT = """BIOLOGY II
1. The diagram shows a nephron.
(a) Name the part labelled X. (2 marks)
(b) Explain how glucose is reabsorbed in the proximal tubule. (4 marks)
2. Describe osmoregulation in freshwater fish. (6 marks)
"""
PAPER_1_TEXT = """1. Which organelle makes ATP? (1) Ribosome (2) Mitochondrion
2. Which is a monomer of starch?
3) Xq@#% %%^& ~~ !!
"""


class PipelineAIClient:
    """Runs ai_service EXTRACT_PAST_PAPER in this process (like the real ai_service)."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    async def run_job(self, job_id, job_type, payload):  # type: ignore[no-untyped-def]
        self.payloads.append(payload)
        try:
            result = await past_paper_extract.run(payload)
        except UserInputError as exc:
            raise AppError(exc.message, code=exc.code, status_code=422) from exc
        return {"job_id": job_id, "job_type": job_type, "result": result}


@pytest.fixture
def pages(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """Mock OCR: what read_pages returns. Change `pages["text"]` in a test."""
    data = {"text": [PAPER_2_TEXT]}

    async def read_pages(file_path: str) -> list[str]:
        return data["text"]

    monkeypatch.setattr(past_paper_extract, "read_pages", read_pages)
    return data


@pytest.fixture
def stored(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    files: dict[str, bytes] = {}

    def upload_bytes(path: str, data: bytes, content_type: str) -> str:
        files[path] = data
        return path

    monkeypatch.setattr(storage, "upload_bytes", upload_bytes)
    return files


@pytest.fixture
async def clean(db_session, admin_in_db):  # type: ignore[no-untyped-def]
    yield
    await db_session.rollback()
    await db_session.execute(delete(PastPaper).where(PastPaper.uploaded_by == ADMIN.id))
    await db_session.execute(delete(AIJob).where(AIJob.job_type == "extract_past_paper"))
    await db_session.commit()


def upload(c, *, year: int = 2019, paper_type: str = "paper_2_structured", data: bytes = PDF,  # type: ignore[no-untyped-def]
           scheme: bytes | None = None):  # fmt: skip
    # Flutter web sends no content type for the file (application/octet-stream).
    files: dict[str, Any] = {"file": ("2019_P2.pdf", data, "application/octet-stream")}
    if scheme is not None:
        files["scheme"] = ("scheme.pdf", scheme, "application/pdf")
    return c.post(URL, data={"year": str(year), "paper_type": paper_type}, files=files)


# --------------------------------------------------------------------------- pipeline (pure)


def test_split_paper_2_into_parts() -> None:
    questions = split_questions(PAPER_2_TEXT, "paper_2_structured")
    assert [q["label"] for q in questions] == ["Q1 (a)", "Q1 (b)", "Q2"]
    assert [q["marks"] for q in questions] == [2, 4, 6]
    assert questions[0]["text"].startswith("The diagram shows a nephron.")
    assert "glucose" in questions[1]["suggested_keywords"]
    # Words from the question frame ("The diagram shows...", "labelled X") are not keywords.
    assert questions[0]["suggested_keywords"] == ["nephron"]


def test_split_paper_1_and_confidence() -> None:
    questions = split_questions(PAPER_1_TEXT, "paper_1_mcq")
    assert [q["label"] for q in questions] == ["Q1", "Q2", "Q3"]
    assert questions[0]["ocr_confidence"] > 0.8
    assert questions[2]["ocr_confidence"] < 0.8  # OCR noise
    assert readability("") == 0.0


# --------------------------------------------------------------------------- auth + validation


async def test_login_and_admin_role_needed(anon_client, client) -> None:
    some = uuid.uuid4()
    for c, code in ((anon_client, 401), (client, 403)):
        assert (await c.get(URL)).status_code == code
        assert (await upload(c)).status_code == code
        assert (await c.get(f"{URL}/{some}/questions")).status_code == code
        put = await c.put(f"{URL}/questions/{some}", json={"model_answer": "x", "keywords": []})
        assert put.status_code == code


@pytest.mark.parametrize(
    ("form", "with_file"),
    [
        ({"year": "1800", "paper_type": "paper_1_mcq"}, True),
        ({"year": "2019", "paper_type": "paper_3"}, True),
        ({"year": "2019", "paper_type": "paper_1_mcq"}, False),
    ],
)
async def test_bad_upload_form_is_422(admin_client, form: dict, with_file: bool) -> None:
    files = {"file": ("p.pdf", PDF, "application/pdf")} if with_file else None
    response = await admin_client.post(URL, data=form, files=files)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_bad_answer_body_is_422(admin_client) -> None:
    some = uuid.uuid4()
    long = await admin_client.put(f"{URL}/questions/{some}", json={"keywords": ["x" * 101]})
    bad_id = await admin_client.put(f"{URL}/questions/nope", json={"keywords": []})
    assert (long.status_code, bad_id.status_code) == (422, 422)


@pytest.mark.db
async def test_not_a_pdf_and_too_large(admin_client, clean, stored, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    not_pdf = await upload(admin_client, data=b"PK\x03\x04 a zip file")
    monkeypatch.setattr(questions_service, "MAX_PAST_PAPER_BYTES", 10)
    too_big = await upload(admin_client, data=PDF + b"x" * 20)

    assert not_pdf.status_code == 415
    assert not_pdf.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    assert too_big.status_code == 413
    assert too_big.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert stored == {}


# --------------------------------------------------------------------------- happy path


@pytest.mark.db
async def test_upload_extract_list_and_save_answer(clean, stored, pages) -> None:  # type: ignore[no-untyped-def]
    ai = PipelineAIClient()
    async with make_api_client(user=ADMIN, ai=ai) as c:
        created = await upload(c, scheme=PDF)
        listed = await c.get(URL)
        paper_id = created.json()["id"]
        questions = await c.get(f"{URL}/{paper_id}/questions")
        first = questions.json()[0]
        saved = await c.put(
            f"{URL}/questions/{first['id']}",
            json={
                "model_answer": " Bowman's capsule ",
                "keywords": ["Bowman", " bowman ", "capsule"],
            },
        )
        again = await c.get(f"{URL}/{paper_id}/questions")

    assert created.status_code == 201, created.text
    paper = created.json()
    assert set(paper) == {"id", "year", "paper_type", "scheme_linked", "extraction",
                          "questions_extracted", "progress", "low_confidence",
                          "outdated_syllabus"}  # fmt: skip
    assert (paper["extraction"], paper["progress"], paper["scheme_linked"]) == (
        "running",
        0.0,
        True,
    )
    assert set(stored) == {f"past_papers/{paper_id}.pdf", f"past_papers/{paper_id}-scheme.pdf"}
    assert ai.payloads[0]["paper_type"] == "paper_2_structured"

    [row] = [p for p in listed.json() if p["id"] == paper_id]
    assert (row["extraction"], row["progress"], row["questions_extracted"]) == ("done", 1.0, 3)
    assert row["low_confidence"] == 0

    assert [q["label"] for q in questions.json()] == ["Q1 (a)", "Q1 (b)", "Q2"]
    assert set(first) == {"id", "label", "marks", "text", "ocr_confidence", "model_answer",
                          "keywords", "suggested_keywords"}  # fmt: skip
    assert (first["marks"], first["model_answer"], first["keywords"]) == (2, None, [])
    assert saved.status_code == 200
    assert saved.json()["model_answer"] == "Bowman's capsule"
    assert saved.json()["keywords"] == ["Bowman", "capsule"]
    assert again.json()[0]["keywords"] == ["Bowman", "capsule"]


@pytest.mark.db
async def test_low_confidence_and_failed_extraction(clean, stored, pages) -> None:  # type: ignore[no-untyped-def]
    async with make_api_client(user=ADMIN, ai=PipelineAIClient()) as c:
        pages["text"] = [PAPER_1_TEXT]
        noisy = (await upload(c, year=2018, paper_type="paper_1_mcq")).json()["id"]
        pages["text"] = ["A cover page with no numbered questions"]
        failed = (await upload(c, year=2017, paper_type="paper_1_mcq")).json()["id"]
        listed = {p["id"]: p for p in (await c.get(URL)).json()}
        duplicate = await upload(c, year=2018, paper_type="paper_1_mcq")

    assert listed[noisy]["extraction"] == "low_confidence"
    assert listed[noisy]["low_confidence"] == 1
    assert listed[failed]["extraction"] == "failed"
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "PAST_PAPER_EXISTS"


@pytest.mark.db
async def test_unknown_paper_and_question_are_404(admin_client, admin_in_db) -> None:  # type: ignore[no-untyped-def]
    some = uuid.uuid4()
    paper = await admin_client.get(f"{URL}/{some}/questions")
    question = await admin_client.put(f"{URL}/questions/{some}", json={"keywords": []})
    assert paper.json()["error"]["code"] == "PAST_PAPER_NOT_FOUND"
    assert question.status_code == 404
    assert question.json()["error"]["code"] == "PAST_PAPER_QUESTION_NOT_FOUND"
