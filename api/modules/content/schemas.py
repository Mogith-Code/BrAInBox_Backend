"""Request / response models (Pydantic) for the content module. Owner: Samni.

Uploads to summarise (summarization module):
    POST /uploads/text   JSON body  -> UploadTextRequest
    POST /uploads/pdf    multipart  -> `file` + `title` (+ `topic_id`) form fields
    GET  /uploads/{id}              -> UploadOut (status + summary)
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.enums import JobStatus

# Same limit as MAX_INPUT_CHARS in ai_service/config.py (about 10,000 words).
MAX_TEXT_CHARS = 60_000
MAX_PDF_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_TITLE_CHARS = 200  # summaries are titled like topics (topics.title is 200 chars)

TEXT_MIME_TYPE = "text/plain"
PDF_MIME_TYPE = "application/pdf"


class ModuleStatus(BaseModel):
    """Response of the placeholder status route."""

    module: str
    status: str


# ---------------------------------------------------------------- uploads: requests
class SummaryOptions(BaseModel):
    """How the summary should look.

    Only what the summarization prompt produces today is accepted. New values (e.g. length
    "short") will be added together with a new prompt version, so old clients keep working.
    """

    model_config = ConfigDict(extra="forbid")  # a misspelt option is an error, not ignored

    length: Literal["medium"] = Field(default="medium", description="About 400 words")
    format: Literal["bullet_points"] = Field(
        default="bullet_points", description="Markdown with short headings and bullet points"
    )


class UploadTextRequest(BaseModel):
    """Plain-text notes to summarise."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "input_type": "text",
                    "title": "Photosynthesis",
                    "text": "Photosynthesis is the process by which green plants make glucose...",
                    "options": {"length": "medium", "format": "bullet_points"},
                }
            ]
        }
    )

    input_type: Literal["text"] = "text"
    title: str = Field(
        min_length=1,
        max_length=MAX_TITLE_CHARS,
        description="What the notes are about, e.g. the topic name",
    )
    text: str = Field(
        min_length=1, max_length=MAX_TEXT_CHARS, description="The Biology notes to summarise"
    )
    topic_id: uuid.UUID | None = Field(
        default=None, description="Optional syllabus topic the notes belong to"
    )
    options: SummaryOptions = Field(default_factory=SummaryOptions)

    @field_validator("title", "text")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty or only whitespace")
        return value.strip()


# ---------------------------------------------------------------- uploads: responses
class UploadError(BaseModel):
    """Why processing failed (same fields as the API error body)."""

    code: str
    message: str


class UploadSummary(BaseModel):
    """The generated summary (a `summaries` row)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    body_md: str  # Markdown
    prompt_version: str | None
    created_at: datetime


class UploadOut(BaseModel):
    """An upload and where its summary is.

    status: queued -> running -> succeeded | failed  (shared.enums.JobStatus)
      * succeeded: `summary` is filled, `error` is null
      * failed:    `error` is filled (see service.INPUT_ERROR_CODES), `summary` is null
      * otherwise: both are null, poll GET /uploads/{upload_id} again
    """

    upload_id: uuid.UUID
    input_type: Literal["text", "pdf"]
    title: str
    topic_id: uuid.UUID | None
    status: JobStatus
    summary: UploadSummary | None = None
    error: UploadError | None = None
    created_at: datetime


# ---------------------------------------------------------------- admin: content library
# Matches BrAInBox_Mobile apps/admin/lib/features/content_review/domain/content_review_models.dart
ContentItemType = Literal["note", "short_note", "diagram"]
ContentStatusValue = Literal["draft", "pending_review", "approved", "rejected", "archived"]


class ContentItemOut(BaseModel):
    """One note, short note or diagram in the admin content library."""

    id: uuid.UUID
    title: str
    type: ContentItemType
    syllabus_code: str | None = None  # topic number, e.g. "5.4"
    unit_number: int | None = None
    status: ContentStatusValue
    is_ai_generated: bool
    model: str | None = None
    prompt_version: str | None = None
    body_markdown: str | None = None  # notes; diagrams: their Mermaid code in a mermaid block
    image_url: str | None = None  # diagrams
    auto_check: str | None = None  # one sentence from the automatic checks, null = nothing to say
    updated_at: datetime


class ContentReviewIn(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class ContentEditIn(BaseModel):
    body_markdown: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)


# ---------------------------------------------------------------- admin: RAG sources
# The admin app has a placeholder screen for these; this is the proposed shape.
RAG_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
MAX_RAG_BYTES = 40 * 1024 * 1024  # 40 MB


class RagSourceOut(BaseModel):
    id: uuid.UUID
    title: str
    source_type: str  # SourceType: syllabus | teachers_guide | approved_note | marking_scheme...
    unit_number: int | None = None
    year: int | None = None
    status: str  # pending | ingesting | ready | failed
    chunk_count: int
    page_count: int | None = None
    error_message: str | None = None
    indexed_at: datetime | None = None
    updated_at: datetime


class RagJobOut(BaseModel):
    job_id: uuid.UUID
    document_id: uuid.UUID | None = None  # null for "reindex everything"


class RagReindexIn(BaseModel):
    document_id: uuid.UUID | None = None  # null = every document
