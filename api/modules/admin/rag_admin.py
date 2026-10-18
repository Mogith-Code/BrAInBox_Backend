"""Admin routes: RAG source documents. Owner: Samni.

Admins upload approved documents (NIE syllabus, teacher guides, approved notes,
marking schemes). Each upload creates a `source_documents` row and a RAG_INGEST job;
the ai_service then chunks + embeds it into `document_chunks`.

Mounted under /api/v1/admin/rag (admin role required by admin/router.py).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile

from api.core.security import CurrentUserDep
from api.modules.admin.schemas import ModuleStatus
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
