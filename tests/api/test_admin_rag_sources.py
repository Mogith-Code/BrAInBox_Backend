"""Admin RAG sources: list, upload, reindex (rag_admin.py). Owner: Samni."""

import uuid
from typing import Any

import pytest
from sqlalchemy import delete, select

from api.core import jobs, storage
from shared.db.models import (
    AIJob,
    SourceDocument,
    Unit,
)
from tests.conftest import ADMIN

ANSWERS = "/api/v1/admin/model-answers"
SOURCES = "/api/v1/admin/rag/sources"
REINDEX = "/api/v1/admin/rag/reindex"
TAG = "admextra"


def option_url(option_id: object) -> str:
    return f"/api/v1/admin/options/{option_id}/misconception"


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """No ai_service here: record the queued jobs and keep uploaded files in memory."""
    payloads: list[dict[str, Any]] = []
    monkeypatch.setattr(jobs, "enqueue_job", lambda job, background: payloads.append(job.input))
    monkeypatch.setattr(storage, "upload_bytes", lambda path, data, content_type: path)
    return payloads


@pytest.fixture
async def clean_sources(db_session, admin_in_db):  # type: ignore[no-untyped-def]
    yield
    await db_session.rollback()
    await db_session.execute(delete(SourceDocument).where(SourceDocument.uploaded_by == ADMIN.id))
    await db_session.execute(delete(AIJob).where(AIJob.requested_by == ADMIN.id))
    await db_session.commit()


async def test_bad_rag_upload_form_is_422(admin_client) -> None:
    files = {"file": ("notes.md", b"# Osmosis", "text/markdown")}
    bad_type = await admin_client.post(
        SOURCES, data={"title": "Notes", "source_type": "blog"}, files=files
    )
    no_file = await admin_client.post(SOURCES, data={"title": "Notes", "source_type": "syllabus"})
    assert (bad_type.status_code, no_file.status_code) == (422, 422)


async def test_rag_upload_list_and_reindex(admin_client, clean_sources, queued, db_session) -> None:  # type: ignore[no-untyped-def]
    unit = (await db_session.execute(select(Unit).limit(1))).scalar_one_or_none()
    form = {"title": "Osmosis teacher guide", "source_type": "teachers_guide", "year": "2024"}
    if unit is not None:
        form["unit_number"] = str(unit.number)
    uploaded = await admin_client.post(
        SOURCES,
        data=form,
        files={"file": ("guide.md", b"# Osmosis\nWater moves...", "text/markdown")},
    )
    assert uploaded.status_code == 202, uploaded.text
    doc_id = uploaded.json()["document_id"]
    assert set(uploaded.json()) == {"job_id", "document_id"}

    listed = await admin_client.get(SOURCES)
    [row] = [d for d in listed.json() if d["id"] == doc_id]
    assert (row["title"], row["source_type"], row["status"]) == (
        "Osmosis teacher guide",
        "teachers_guide",
        "pending",
    )
    one = await admin_client.post(REINDEX, json={"document_id": doc_id})
    everything = await admin_client.post(REINDEX)
    missing = await admin_client.post(REINDEX, json={"document_id": str(uuid.uuid4())})

    assert (one.status_code, everything.status_code) == (202, 202)
    assert everything.json()["document_id"] is None
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "SOURCE_NOT_FOUND"
    assert queued == [
        {"document_id": doc_id},
        {"document_id": doc_id, "force": True},
        {"all": True, "force": True},
    ]


async def test_rag_upload_rejects_bad_files(admin_client, clean_sources, queued) -> None:  # type: ignore[no-untyped-def]
    form = {"title": "Bad file", "source_type": "syllabus"}
    exe = await admin_client.post(
        SOURCES, data=form, files={"file": ("x.exe", b"MZ", "application/octet-stream")}
    )
    fake_pdf = await admin_client.post(
        SOURCES, data=form, files={"file": ("x.pdf", b"hello", "application/pdf")}
    )
    empty = await admin_client.post(
        SOURCES, data=form, files={"file": ("x.txt", b"", "text/plain")}
    )
    bad_unit = await admin_client.post(
        SOURCES,
        data={**form, "unit_number": "99999"},
        files={"file": ("x.txt", b"ok", "text/plain")},
    )
    assert (exe.status_code, fake_pdf.status_code, empty.status_code) == (415, 415, 422)
    assert bad_unit.json()["error"]["code"] == "UNIT_NOT_FOUND"
    assert queued == []


@pytest.mark.parametrize(
    ("method", "path", "kwargs"), [("get", SOURCES, {}), ("post", REINDEX, {})]
)
async def test_login_and_admin_role_needed(anon_client, client, method, path, kwargs) -> None:  # type: ignore[no-untyped-def]
    assert (await getattr(anon_client, method)(path, **kwargs)).status_code == 401
    assert (await getattr(client, method)(path, **kwargs)).status_code == 403


@pytest.mark.parametrize(("method", "path", "body"), [("post", REINDEX, {"document_id": "nope"})])
async def test_bad_bodies_are_422(admin_client, method: str, path: str, body: dict) -> None:
    response = await getattr(admin_client, method)(path, json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
