"""Admin routes: RAG source documents. Owner: Samni.

Admins upload approved documents (NIE syllabus, teacher guides, approved notes,
marking schemes). Each upload creates a `source_documents` row and a RAG_INGEST job;
the ai_service then chunks + embeds it into `document_chunks`.

Mounted under /api/v1/admin/rag (admin role required by admin/router.py).

    GET  /admin/rag/sources      the source documents with their ingestion status
    POST /admin/rag/sources      multipart upload -> 202 {job_id, document_id} (RAG_INGEST job)
    POST /admin/rag/reindex      {document_id?} -> 202 {job_id}; no id = every document

The /documents routes below are older placeholders, kept until the app stops calling them.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Body, File, Form, UploadFile, status

from api.core.database import SessionDep
from api.core.security import CurrentUserDep
from api.modules.admin import service as admin_service
from api.modules.admin.schemas import ModuleStatus
from api.modules.content import service as content_service
from api.modules.content.schemas import RagJobOut, RagReindexIn, RagSourceOut
from shared.enums import SourceType

router = APIRouter(prefix="/rag", tags=["Admin: RAG documents"])


@router.get("/status", response_model=ModuleStatus, summary="Placeholder: admin area status")
async def area_status(admin: CurrentUserDep) -> ModuleStatus:
    return ModuleStatus(module="rag_admin", status="todo")


@router.post("/documents", response_model=ModuleStatus, summary="Upload a source document")
async def upload_document(
    admin: CurrentUserDep,
    file: Annotated[UploadFile, File(description="PDF, DOCX, TXT or Markdown")],
    title: Annotated[str, Form()],
    source_type: Annotated[SourceType, Form()],
    unit_number: Annotated[int | None, Form(ge=1, le=10)] = None,
    year: Annotated[int | None, Form()] = None,
) -> ModuleStatus:
    # TODO(Samni):
    #   1. storage.upload_bytes(f"rag_sources/{source_type}/{file.filename}", ...)
    #   2. create the source_documents row (status=pending, sha256 of the bytes)
    #   3. jobs.create_job(session, JobType.RAG_INGEST, {"document_id": ...}) + enqueue_job
    #   4. return the document + job id
    return ModuleStatus(module="rag_admin", status="todo")


@router.get("/documents", response_model=ModuleStatus, summary="List source documents")
async def list_documents(admin: CurrentUserDep) -> ModuleStatus:
    # TODO(Samni): paginated list with status, chunk_count, error_message (use Page[T]).
    return ModuleStatus(module="rag_admin", status="todo")


@router.post(
    "/documents/{document_id}/reindex", response_model=ModuleStatus, summary="Re-ingest a document"
)
async def reindex_document(document_id: uuid.UUID, admin: CurrentUserDep) -> ModuleStatus:
    # TODO(Samni): create a RAG_INGEST job with {"document_id": ..., "force": true}.
    return ModuleStatus(module="rag_admin", status="todo")


# ---------------------------------------------------------------- sources (built)


@router.get("/sources", response_model=list[RagSourceOut], summary="RAG source documents")
async def list_sources(admin: CurrentUserDep, session: SessionDep) -> list[RagSourceOut]:
    """Last changed first (max 200). `status`: pending | ingesting | ready | failed."""
    return await content_service.admin_list_rag_sources(session)


@router.post(
    "/sources",
    response_model=RagJobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a source document (it is chunked + embedded in the background)",
)
async def upload_source(
    admin: CurrentUserDep,
    session: SessionDep,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(description="PDF, DOCX, TXT or Markdown, max 40 MB")],
    title: Annotated[str, Form(min_length=2, max_length=300)],
    source_type: Annotated[SourceType, Form()],
    unit_number: Annotated[int | None, Form(ge=1)] = None,
    year: Annotated[int | None, Form(ge=1990, le=2100)] = None,
) -> RagJobOut:
    """Poll `GET /api/v1/jobs/{job_id}` or `GET /admin/rag/sources` for the status.

    Errors: 404 `UNIT_NOT_FOUND` · 413 `FILE_TOO_LARGE` · 415 `UNSUPPORTED_FILE_TYPE` ·
    422 `EMPTY_FILE` / `VALIDATION_ERROR`."""
    out = await content_service.admin_upload_rag_source(
        session,
        admin.id,
        file=file,
        title=title,
        source_type=source_type,
        unit_number=unit_number,
        year=year,
        background_tasks=background_tasks,
    )
    await admin_service.record_audit(
        session, admin, "rag.upload", "source_document", out.document_id
    )
    return out


@router.post(
    "/reindex",
    response_model=RagJobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-index one source document, or all of them",
)
async def reindex(
    admin: CurrentUserDep,
    session: SessionDep,
    background_tasks: BackgroundTasks,
    req: Annotated[RagReindexIn | None, Body()] = None,
) -> RagJobOut:
    """Body optional: `{document_id}` for one document; empty / null = every document (one job).
    Errors: 404 `SOURCE_NOT_FOUND`."""
    document_id = req.document_id if req else None
    out = await content_service.admin_reindex(session, admin.id, document_id, background_tasks)
    await admin_service.record_audit(
        session, admin, "rag.reindex", "source_document", document_id or "all"
    )
    return out
