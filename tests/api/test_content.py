"""Tests for the content module: uploads to summarise. Owner: Samni."""

import functools
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import delete

from ai_service.main import create_app as create_ai_app
from ai_service.providers import set_providers
from ai_service.providers.storage import LocalStorage
from api.core import jobs, storage
from api.core.ai_client import AIClient, get_ai_client, input_error_from
from api.core.config import get_settings as get_api_settings
from api.core.database import get_session
from api.core.errors import AppError, ServiceUnavailableError
from api.core.security import get_current_user
from api.main import create_app
from api.modules.content import repository, service
from api.modules.content.schemas import MAX_TEXT_CHARS, UploadTextRequest
from shared.db.models import AIJob, Summary, Upload, User
from shared.enums import JobStatus, JobType, UserRole
from tests.conftest import SERVICE_TOKEN, STUDENT, _client
from tests.samples import OSMOSIS_NOTES, make_pdf

NOTES = "Osmosis is the movement of water across a partially permeable membrane."
SUMMARY_RESULT = {
    "title": "Osmosis",
    "body_md": "## Osmosis\n- Water moves across a partially permeable membrane.",
    "key_points": ["Water moves from high to low water potential"],
    "key_terms": ["osmosis"],
    "topic_id": None,
    "source": "notes",
    "citations": [],
    "prompt_version": "summarization/summarize_topic.v1",
}
PDF_BYTES = make_pdf(OSMOSIS_NOTES)
ORIGINAL_ASYNC_CLIENT = httpx.AsyncClient


# --------------------------------------------------------------------------- helpers


class FakeAIClient:
    """Stands in for the ai_service: SUMMARIZE_UPLOAD returns a fixed summary (or fails)."""

    def __init__(
        self,
        fail: bool = False,
        result: dict | None = None,  # type: ignore[type-arg]
        error: AppError | None = None,
    ):
        self.fail = fail
        self.error = error
        self.result = SUMMARY_RESULT if result is None else result
        self.calls: list[tuple[str, dict]] = []  # type: ignore[type-arg]

    async def run_job(self, job_id, job_type, payload):  # type: ignore[no-untyped-def]
        self.calls.append((job_type, payload))
        if self.error:
            raise self.error
        if self.fail:  # e.g. the ai_service is down or timed out
            raise ServiceUnavailableError(
                "The AI service is not available right now", code="AI_SERVICE_UNAVAILABLE"
            )
        return {"job_id": job_id, "job_type": job_type, "result": self.result}


class FakeSession:
    """Just enough of AsyncSession for code that only adds rows and commits."""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        pass

    async def refresh(self, obj: object) -> None:
        pass


def _app(user=STUDENT, ai=None, session=None):  # type: ignore[no-untyped-def]
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: user
    if ai is not None:
        app.dependency_overrides[get_ai_client] = lambda: ai
    if session is not None:
        app.dependency_overrides[get_session] = lambda: session
    return app


def make_upload(
    status: JobStatus = JobStatus.QUEUED,
    user_id: uuid.UUID = STUDENT.id,
    mime_type: str = "text/plain",
) -> Upload:
    return Upload(
        id=uuid.uuid4(),
        user_id=user_id,
        topic_id=None,
        file_name="Osmosis",
        file_path="",
        mime_type=mime_type,
        size_bytes=len(NOTES),
        processing_status=status,
        created_at=datetime.now(UTC),
    )


def make_summary(upload: Upload) -> Summary:
    return Summary(
        id=uuid.uuid4(),
        user_id=upload.user_id,
        upload_id=upload.id,
        topic_id=None,
        body_md=SUMMARY_RESULT["body_md"],
        prompt_version=SUMMARY_RESULT["prompt_version"],
        created_at=datetime.now(UTC),
    )


def make_job(text: str = NOTES, error: str | None = None) -> AIJob:
    return AIJob(
        id=uuid.uuid4(),
        job_type=JobType.SUMMARIZE_UPLOAD,
        status=JobStatus.FAILED if error else JobStatus.QUEUED,
        input={"topic_title": "Osmosis", "text": text},
        error=error,
        attempts=0,
    )


def fields(response) -> list[str]:  # type: ignore[no-untyped-def]
    """Invalid fields listed in a 422 VALIDATION_ERROR body."""
    return [d["field"] for d in response.json()["error"]["details"]]


def pdf_upload(data: bytes = PDF_BYTES, content_type: str = "application/pdf"):  # type: ignore[no-untyped-def]
    return {"file": ("notes.pdf", data, content_type)}


@pytest.fixture
def queued(monkeypatch):  # type: ignore[no-untyped-def]
    """Replace the DB writes of POST /uploads/*; records what was created and scheduled."""
    created: dict = {"scheduled": []}  # type: ignore[type-arg]
    job = make_job()

    async def fake_create_upload(session, *, upload_id=None, **fields):  # type: ignore[no-untyped-def]
        created["upload"] = {"upload_id": upload_id, **fields}
        return Upload(
            id=upload_id or uuid.uuid4(),
            processing_status=JobStatus.QUEUED,
            created_at=datetime.now(UTC),
            **fields,
        )

    async def fake_create_job(session, job_type, payload, requested_by=None):  # type: ignore[no-untyped-def]
        created["job"] = (job_type, payload, requested_by)
        return job

    async def fake_process_upload(upload_id, job_id, ai):  # type: ignore[no-untyped-def]
        created["scheduled"].append((upload_id, job_id))

    monkeypatch.setattr(repository, "create_upload", fake_create_upload)
    monkeypatch.setattr(jobs, "create_job", fake_create_job)
    monkeypatch.setattr(service, "process_upload", fake_process_upload)
    created["job_id"] = job.id
    return created


@pytest.fixture
def real_ai_client(monkeypatch) -> AIClient:  # type: ignore[no-untyped-def]
    """An AIClient that talks to the real ai_service app (with fake providers), in memory."""
    transport = httpx.ASGITransport(app=create_ai_app())
    monkeypatch.setattr(
        httpx, "AsyncClient", functools.partial(ORIGINAL_ASYNC_CLIENT, transport=transport)
    )
    return AIClient("http://ai-service", SERVICE_TOKEN)


# --------------------------------------------------------------------------- placeholders


async def test_content_status_requires_login(anon_client):
    response = await anon_client.get("/api/v1/content/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_content_status_placeholder(client):
    response = await client.get("/api/v1/content/status")
    assert response.status_code == 200
    assert response.json() == {"module": "content", "status": "todo"}


# --------------------------------------------------------------------------- text: schema


def test_text_request_defaults_and_strips():
    req = UploadTextRequest(title="  Osmosis ", text=f"  {NOTES}\n")
    assert req.title == "Osmosis"
    assert req.text == NOTES
    assert req.input_type == "text"
    assert req.options.model_dump() == {"length": "medium", "format": "bullet_points"}


async def test_upload_text_requires_login(anon_client):
    response = await anon_client.post("/api/v1/uploads/text", json={"title": "x", "text": NOTES})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize(
    ("body", "bad_field"),
    [
        ({"title": "Osmosis"}, "body.text"),  # missing text
        ({"text": NOTES}, "body.title"),  # missing title
        ({"title": "Osmosis", "text": "   \n "}, "body.text"),  # empty text
        ({"title": "  ", "text": NOTES}, "body.title"),  # empty title
        ({"title": "Osmosis", "text": "a" * (MAX_TEXT_CHARS + 1)}, "body.text"),  # too long
        ({"title": "Osmosis", "text": NOTES, "input_type": "pdf"}, "body.input_type"),
        ({"title": "Osmosis", "text": NOTES, "topic_id": "not-a-uuid"}, "body.topic_id"),
        (
            {"title": "Osmosis", "text": NOTES, "options": {"length": "short"}},
            "body.options.length",
        ),
        (
            {"title": "Osmosis", "text": NOTES, "options": {"format": "essay"}},
            "body.options.format",
        ),
        ({"title": "Osmosis", "text": NOTES, "options": {"colour": "red"}}, "body.options.colour"),
    ],
)
async def test_upload_text_rejects_invalid_input(client, body, bad_field):
    response = await client.post("/api/v1/uploads/text", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert bad_field in fields(response)


async def test_upload_text_is_accepted_and_queued(queued):
    """Valid text -> 202 "queued" at once, the job payload is right and processing is scheduled."""
    async with _client(_app(ai=FakeAIClient(), session=FakeSession())) as c:
        response = await c.post(
            "/api/v1/uploads/text", json={"input_type": "text", "title": "Osmosis", "text": NOTES}
        )

    assert response.status_code == 202, response.text
    body = response.json()
    assert (body["status"], body["summary"], body["error"]) == ("queued", None, None)
    assert body["input_type"] == "text"

    assert queued["upload"]["user_id"] == STUDENT.id
    assert queued["upload"]["mime_type"] == "text/plain"
    job_type, payload, requested_by = queued["job"]
    assert job_type == JobType.SUMMARIZE_UPLOAD
    assert requested_by == STUDENT.id
    assert payload["topic_title"] == "Osmosis"
    assert payload["text"] == NOTES
    assert payload["upload_id"] == body["upload_id"]
    assert payload["options"] == {"length": "medium", "format": "bullet_points"}
    assert queued["scheduled"] == [(uuid.UUID(body["upload_id"]), queued["job_id"])]


# --------------------------------------------------------------------------- PDF


async def test_upload_pdf_requires_login(anon_client):
    response = await anon_client.post(
        "/api/v1/uploads/pdf", files=pdf_upload(), data={"title": "Osmosis"}
    )
    assert response.status_code == 401


async def test_pdf_is_saved_and_queued(queued, monkeypatch):
    saved: list[tuple[str, bytes, str]] = []

    def fake_upload_bytes(path: str, data: bytes, content_type: str) -> str:
        saved.append((path, data, content_type))
        return path

    monkeypatch.setattr(storage, "upload_bytes", fake_upload_bytes)
    async with _client(_app(ai=FakeAIClient(), session=FakeSession())) as c:
        response = await c.post(
            "/api/v1/uploads/pdf", files=pdf_upload(), data={"title": " Osmosis "}
        )

    assert response.status_code == 202, response.text
    body = response.json()
    assert (body["status"], body["input_type"], body["title"]) == ("queued", "pdf", "Osmosis")

    [(path, data, content_type)] = saved
    assert path == f"uploads/{STUDENT.id}/{body['upload_id']}.pdf"
    assert (data, content_type) == (PDF_BYTES, "application/pdf")
    assert queued["upload"]["file_path"] == path
    assert queued["upload"]["size_bytes"] == len(PDF_BYTES)
    _, payload, _ = queued["job"]
    assert payload["file_path"] == path
    assert payload["mime_type"] == "application/pdf"
    assert "text" not in payload  # the ai_service extracts it from the file
    assert len(queued["scheduled"]) == 1


async def test_pdf_is_not_stored_when_storage_fails(client, monkeypatch):
    def broken_upload_bytes(path: str, data: bytes, content_type: str) -> str:
        raise ServiceUnavailableError("Storage is not configured", code="STORAGE_NOT_CONFIGURED")

    async def must_not_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("no upload row for a file that was not saved")

    monkeypatch.setattr(storage, "upload_bytes", broken_upload_bytes)
    monkeypatch.setattr(repository, "create_upload", must_not_run)
    response = await client.post(
        "/api/v1/uploads/pdf", files=pdf_upload(), data={"title": "Osmosis"}
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "STORAGE_NOT_CONFIGURED"


@pytest.mark.parametrize(
    ("data", "content_type", "status", "code"),
    [
        (PDF_BYTES, "text/plain", 415, "UNSUPPORTED_FILE_TYPE"),  # wrong content type
        (b"just some text", "application/pdf", 415, "UNSUPPORTED_FILE_TYPE"),  # not a real PDF
        (b"", "application/pdf", 422, "EMPTY_FILE"),
    ],
)
async def test_invalid_pdf_is_rejected(client, data, content_type, status, code):
    response = await client.post(
        "/api/v1/uploads/pdf", files=pdf_upload(data, content_type), data={"title": "Osmosis"}
    )
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


async def test_too_large_pdf_is_rejected(client, monkeypatch):
    monkeypatch.setattr(service, "MAX_PDF_BYTES", 10)
    response = await client.post(
        "/api/v1/uploads/pdf", files=pdf_upload(), data={"title": "Osmosis"}
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"


@pytest.mark.parametrize(
    ("files", "data", "bad_field"),
    [
        (None, {"title": "Osmosis"}, "body.file"),  # no file
        (pdf_upload(), {}, "body.title"),  # no title
        (pdf_upload(), {"title": "   "}, "body.title"),  # empty title
    ],
)
async def test_pdf_missing_fields(client, files, data, bad_field):
    response = await client.post("/api/v1/uploads/pdf", files=files, data=data)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert bad_field in fields(response)


# --------------------------------------------------------------------------- storage (dev)


def test_without_a_bucket_files_go_to_the_local_folder(monkeypatch, tmp_path):
    settings = get_api_settings()
    monkeypatch.setattr(settings, "STORAGE_BUCKET", "")
    monkeypatch.setattr(settings, "LOCAL_STORAGE_DIR", str(tmp_path))

    assert storage.upload_bytes("uploads/u1/a.pdf", b"%PDF-1.4", "application/pdf")
    assert (tmp_path / "uploads" / "u1" / "a.pdf").read_bytes() == b"%PDF-1.4"
    with pytest.raises(ValueError, match="outside the storage folder"):
        storage.upload_bytes("../escape.pdf", b"%PDF-1.4", "application/pdf")


# --------------------------------------------------------------------------- processing (no DB)


async def test_completed_job_saves_the_summary():
    session, upload, job = FakeSession(), make_upload(), make_job()

    await service.run_upload_job(session, upload, job, FakeAIClient())  # type: ignore[arg-type]

    assert job.status == JobStatus.SUCCEEDED
    assert upload.processing_status == JobStatus.SUCCEEDED
    [summary] = [o for o in session.added if isinstance(o, Summary)]
    assert summary.upload_id == upload.id
    assert summary.user_id == STUDENT.id
    assert summary.body_md == SUMMARY_RESULT["body_md"]
    assert summary.prompt_version == SUMMARY_RESULT["prompt_version"]


async def test_failed_job_marks_the_upload_failed():
    session, upload, job = FakeSession(), make_upload(), make_job()

    await service.run_upload_job(session, upload, job, FakeAIClient(fail=True))  # type: ignore[arg-type]

    assert job.status == JobStatus.FAILED
    assert job.error == "AI_SERVICE_UNAVAILABLE: The AI service is not available right now"
    assert upload.processing_status == JobStatus.FAILED
    assert not [o for o in session.added if isinstance(o, Summary)]


async def test_input_error_keeps_its_code_on_the_job():
    session, upload, job = FakeSession(), make_upload(), make_job()
    error = AppError("Only English notes can be summarised for now", code="NOT_ENGLISH")

    await service.run_upload_job(session, upload, job, FakeAIClient(error=error))  # type: ignore[arg-type]

    assert job.error == "NOT_ENGLISH: Only English notes can be summarised for now"
    assert upload.processing_status == JobStatus.FAILED


async def test_job_without_summary_text_is_a_failure():
    session, upload, job = FakeSession(), make_upload(), make_job()

    await service.run_upload_job(session, upload, job, FakeAIClient(result={"title": "x"}))  # type: ignore[arg-type]

    assert upload.processing_status == JobStatus.FAILED
    assert not [o for o in session.added if isinstance(o, Summary)]


# --------------------------------------------------------------------------- api <-> ai_service


async def test_contract_success_through_the_real_ai_service(real_ai_client):
    session, upload, job = FakeSession(), make_upload(), make_job(text=OSMOSIS_NOTES)

    await service.run_upload_job(session, upload, job, real_ai_client)

    assert upload.processing_status == JobStatus.SUCCEEDED
    [summary] = [o for o in session.added if isinstance(o, Summary)]
    assert summary.prompt_version == "summarization/summarize_topic.v1"


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("Page 3 of 10", "EMPTY_NOTES"),  # nothing left after cleaning
        ("ආශ්‍රැතිය යනු අර්ධ පාරගම්‍ය පටලයක් හරහා ජලය චලනය වීමයි. " * 3, "NOT_ENGLISH"),
    ],
)
async def test_contract_input_errors_reach_the_student(real_ai_client, text, code):
    session, upload, job = FakeSession(), make_upload(), make_job(text=text)

    await service.run_upload_job(session, upload, job, real_ai_client)

    assert upload.processing_status == JobStatus.FAILED
    error = service.failure_error(job.error)
    assert error.code == code
    assert error.message  # the pipeline's message, shown to the student


async def test_contract_bad_request_is_not_blamed_on_the_student(real_ai_client):
    with pytest.raises(ServiceUnavailableError):
        await real_ai_client.run_job("j1", "not-a-job-type", {})  # ai_service: VALIDATION_ERROR


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (
            httpx.Response(422, json={"error": {"code": "EMPTY_NOTES", "message": "m"}}),
            "EMPTY_NOTES",
        ),
        (httpx.Response(422, json={"error": {"code": "VALIDATION_ERROR", "message": "m"}}), None),
        (httpx.Response(500, json={"error": {"code": "INTERNAL_ERROR", "message": "m"}}), None),
        (
            httpx.Response(401, json={"error": {"code": "INVALID_SERVICE_TOKEN", "message": "m"}}),
            None,
        ),
        (httpx.Response(422, text="not json"), None),
    ],
)
def test_input_error_from(response, code):
    error = input_error_from(response)
    assert (error.code if error else None) == code


# --------------------------------------------------------------------------- responses


def test_failure_error_shows_only_input_errors():
    assert service.failure_error("NOT_ENGLISH: Only English notes").code == "NOT_ENGLISH"
    assert service.failure_error("NOT_ENGLISH: Only English notes").message == "Only English notes"
    for hidden in ("AI_SERVICE_UNAVAILABLE: down", "KeyError: 'x'", "", None):
        assert service.failure_error(hidden).code == "SUMMARIZATION_FAILED"


def test_upload_out_for_each_status():
    queued = service.upload_out(make_upload(JobStatus.QUEUED))
    assert (queued.summary, queued.error) == (None, None)

    done_upload = make_upload(JobStatus.SUCCEEDED)
    done = service.upload_out(done_upload, make_summary(done_upload))
    assert done.summary is not None
    assert done.summary.body_md == SUMMARY_RESULT["body_md"]
    assert done.error is None

    failed_upload = make_upload(JobStatus.FAILED)
    failed = service.upload_out(failed_upload, make_summary(failed_upload))
    assert failed.summary is None  # never show a summary for a failed upload
    assert failed.error is not None
    assert failed.error.code == "SUMMARIZATION_FAILED"

    assert service.upload_out(make_upload(mime_type="application/pdf")).input_type == "pdf"


# --------------------------------------------------------------------------- GET (no DB)


@pytest.fixture
def stored(monkeypatch):  # type: ignore[no-untyped-def]
    """Replace the repository reads with in-memory {upload_id: (upload, summary, job)}."""
    rows: dict[uuid.UUID, tuple[Upload, Summary | None, AIJob | None]] = {}

    async def fake_get_upload(session, upload_id):  # type: ignore[no-untyped-def]
        return rows[upload_id][0] if upload_id in rows else None

    async def fake_get_summary(session, upload_id):  # type: ignore[no-untyped-def]
        return rows[upload_id][1]

    async def fake_get_upload_job(session, upload):  # type: ignore[no-untyped-def]
        return rows[upload.id][2]

    monkeypatch.setattr(repository, "get_upload", fake_get_upload)
    monkeypatch.setattr(repository, "get_summary_for_upload", fake_get_summary)
    monkeypatch.setattr(repository, "get_upload_job", fake_get_upload_job)
    return rows


async def test_get_completed_upload_returns_the_summary(client, stored):
    upload = make_upload(JobStatus.SUCCEEDED)
    stored[upload.id] = (upload, make_summary(upload), None)

    response = await client.get(f"/api/v1/uploads/{upload.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["summary"]["body_md"] == SUMMARY_RESULT["body_md"]
    assert body["summary"]["prompt_version"] == SUMMARY_RESULT["prompt_version"]
    assert body["error"] is None


async def test_get_failed_upload_returns_a_generic_error(client, stored):
    upload = make_upload(JobStatus.FAILED)
    job = make_job(error="AI_SERVICE_UNAVAILABLE: The AI service is not available right now")
    stored[upload.id] = (upload, None, job)

    response = await client.get(f"/api/v1/uploads/{upload.id}")

    assert response.status_code == 200  # the request worked; the processing failed
    body = response.json()
    assert body["status"] == "failed"
    assert body["summary"] is None
    assert body["error"]["code"] == "SUMMARIZATION_FAILED"


async def test_get_failed_upload_explains_input_errors(client, stored):
    upload = make_upload(JobStatus.FAILED, mime_type="application/pdf")
    job = make_job(error="NO_TEXT_IN_FILE: We could not find any text in this file.")
    stored[upload.id] = (upload, None, job)

    body = (await client.get(f"/api/v1/uploads/{upload.id}")).json()

    assert body["error"] == {
        "code": "NO_TEXT_IN_FILE",
        "message": "We could not find any text in this file.",
    }


async def test_get_running_upload_has_no_summary_yet(client, stored):
    upload = make_upload(JobStatus.RUNNING)
    stored[upload.id] = (upload, None, None)

    body = (await client.get(f"/api/v1/uploads/{upload.id}")).json()

    assert (body["status"], body["summary"], body["error"]) == ("running", None, None)


async def test_get_unknown_upload(client, stored):
    response = await client.get(f"/api/v1/uploads/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "UPLOAD_NOT_FOUND"


async def test_get_upload_of_another_student(client, admin_client, stored):
    upload = make_upload(JobStatus.QUEUED, user_id=uuid.uuid4())
    stored[upload.id] = (upload, None, None)

    response = await client.get(f"/api/v1/uploads/{upload.id}")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"

    assert (await admin_client.get(f"/api/v1/uploads/{upload.id}")).status_code == 200


async def test_get_upload_requires_login(anon_client):
    response = await anon_client.get(f"/api/v1/uploads/{uuid.uuid4()}")
    assert response.status_code == 401


# --------------------------------------------------------------------------- full flow (DB)


@pytest.fixture
async def student_in_db(db_session):
    """The test student as a real user row; their uploads and jobs are removed afterwards."""
    user = await db_session.get(User, STUDENT.id)
    if user is None:
        db_session.add(
            User(id=STUDENT.id, firebase_uid=STUDENT.firebase_uid, role=UserRole.STUDENT)
        )
        await db_session.commit()
    yield
    for stmt in (
        delete(Upload).where(Upload.user_id == STUDENT.id),  # summaries are deleted with it
        delete(AIJob).where(AIJob.requested_by == STUDENT.id),
        delete(User).where(User.id == STUDENT.id),
    ):
        await db_session.execute(stmt)
    await db_session.commit()


@pytest.fixture
def shared_local_storage(monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
    """The api writes and the ai_service reads the same temporary folder, like in dev."""
    monkeypatch.setattr(get_api_settings(), "STORAGE_BUCKET", "")
    monkeypatch.setattr(get_api_settings(), "LOCAL_STORAGE_DIR", str(tmp_path))
    set_providers(storage=LocalStorage(str(tmp_path)))
    return tmp_path


@pytest.mark.db
async def test_text_upload_flow_until_completed(student_in_db):
    ai = FakeAIClient()
    async with _client(_app(ai=ai)) as c:
        accepted = await c.post("/api/v1/uploads/text", json={"title": "Osmosis", "text": NOTES})
        assert accepted.status_code == 202, accepted.text
        assert accepted.json()["status"] == "queued"

        # The background task has finished once the test client returns.
        upload_id = accepted.json()["upload_id"]
        done = await c.get(f"/api/v1/uploads/{upload_id}")

    assert done.status_code == 200
    body = done.json()
    assert body["status"] == "succeeded"
    assert body["summary"]["body_md"] == SUMMARY_RESULT["body_md"]
    assert body["error"] is None
    [(job_type, payload)] = ai.calls
    assert job_type == "summarize_upload"
    assert payload["text"] == NOTES


@pytest.mark.db
async def test_text_upload_flow_when_ai_fails(student_in_db):
    async with _client(_app(ai=FakeAIClient(fail=True))) as c:
        accepted = await c.post("/api/v1/uploads/text", json={"title": "Osmosis", "text": NOTES})
        assert accepted.status_code == 202
        failed = await c.get(f"/api/v1/uploads/{accepted.json()['upload_id']}")

    body = failed.json()
    assert body["status"] == "failed"
    assert body["summary"] is None
    assert body["error"]["code"] == "SUMMARIZATION_FAILED"


@pytest.mark.db
async def test_text_upload_with_unknown_topic(student_in_db):
    async with _client(_app(ai=FakeAIClient())) as c:
        response = await c.post(
            "/api/v1/uploads/text",
            json={"title": "Osmosis", "text": NOTES, "topic_id": str(uuid.uuid4())},
        )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TOPIC_NOT_FOUND"


@pytest.mark.db
async def test_pdf_flow_through_the_real_ai_service(
    student_in_db, shared_local_storage, real_ai_client
):
    """Everything real except Gemini (fake LLM): storage folder, PDF extraction, both services."""
    async with _client(_app(ai=real_ai_client)) as c:
        accepted = await c.post(
            "/api/v1/uploads/pdf", files=pdf_upload(), data={"title": "Osmosis"}
        )
        assert accepted.status_code == 202, accepted.text
        done = await c.get(f"/api/v1/uploads/{accepted.json()['upload_id']}")

    body = done.json()
    assert body["status"] == "succeeded", body
    assert body["input_type"] == "pdf"
    assert body["summary"]["body_md"]
    assert list(shared_local_storage.rglob("*.pdf"))  # the file was kept


@pytest.mark.db
async def test_scanned_pdf_flow_explains_the_error(
    student_in_db, shared_local_storage, real_ai_client
):
    async with _client(_app(ai=real_ai_client)) as c:
        accepted = await c.post(
            "/api/v1/uploads/pdf", files=pdf_upload(make_pdf("")), data={"title": "Osmosis"}
        )
        assert accepted.status_code == 202
        failed = await c.get(f"/api/v1/uploads/{accepted.json()['upload_id']}")

    body = failed.json()
    assert body["status"] == "failed"
    assert body["error"]["code"] == "NO_TEXT_IN_FILE"
