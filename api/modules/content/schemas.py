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
