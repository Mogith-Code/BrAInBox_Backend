"""Request / response models for the Learn tab (/api/v1/learn). Owner: Samni.

JSON keys are snake_case. Lists are {"items": [...], "total": n} (uploads also have page/size).
Path ids accept the UUID or the public code ("biology", "u6", "bio-6.1").
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from api.modules.learn.mastery import MasteryLevel
from shared.enums import NoteDepth, NoteKind, SummaryLength, TopicProgressStatus

JobKind = Literal["notes", "upload_summary"]
LearnJobStatus = Literal["queued", "running", "done", "failed"]
NoteSourceOut = Literal["ai", "manual", "upload"]


# ---------------------------------------------------------------- shared bits
class SubjectRef(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class UnitRef(BaseModel):
    id: uuid.UUID
    code: str | None
    number: int
    title: str


class TopicRef(BaseModel):
    id: uuid.UUID
    code: str | None
    number: str  # e.g. "6.1"
    title: str


class MasteryOut(BaseModel):
    mastery_percent: int
    mastery_level: MasteryLevel
    is_weak: bool


# ---------------------------------------------------------------- subjects / units / topics
class SubjectOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    level: str
    available: bool
    syllabus_version: str | None
    unit_count: int


class SubjectList(BaseModel):
    items: list[SubjectOut]
    total: int


class UnitSummaryOut(BaseModel):
    id: uuid.UUID
    code: str | None
    number: int
    title: str
    icon_key: str | None
    order: int
    topic_count: int
    mastery_percent: int
    mastery_level: MasteryLevel


class UnitList(BaseModel):
    items: list[UnitSummaryOut]
    total: int


class UnitTopicOut(BaseModel):
    id: uuid.UUID
    code: str | None
    number: str
    title: str
    order: int
    status: TopicProgressStatus
    progress_percent: int
    mastery_percent: int
    mastery_level: MasteryLevel
    is_weak: bool
    is_outdated: bool


class UnitDetailOut(UnitSummaryOut):
    subject: SubjectRef
    mastered_count: int
    weak_count: int
    topics: list[UnitTopicOut]


class Breadcrumb(BaseModel):
    subject: SubjectRef
    unit: UnitRef


class TopicDetailOut(BaseModel):
    id: uuid.UUID
    code: str | None
    number: str
    title: str
    description: str | None
    order: int
    breadcrumb: Breadcrumb
    status: TopicProgressStatus
    progress_percent: int
    seconds_spent: int
    last_opened_at: datetime | None
    mastery: MasteryOut
    is_bookmarked: bool
    syllabus_version: str | None
    is_outdated: bool
    has_full_notes: bool
    has_short_notes: bool


# ---------------------------------------------------------------- notes
class NoteOut(BaseModel):
    id: uuid.UUID
    topic_id: uuid.UUID
    type: NoteKind
    depth: str | None
    title: str
    blocks: list[dict[str, Any]]
    read_minutes: int
    ai_generated: bool
    source: NoteSourceOut
    is_own: bool  # True = the student's own note, False = the official note
    created_at: datetime


class GenerateNotesRequest(BaseModel):
    type: NoteKind = NoteKind.FULL
    depth: NoteDepth = NoteDepth.STANDARD
    include_examples: bool = True
    include_past_paper_tips: bool = True


class JobAccepted(BaseModel):
    job_id: uuid.UUID
    status: LearnJobStatus


class JobOut(BaseModel):
    id: uuid.UUID
    kind: JobKind
    status: LearnJobStatus
    topic_id: uuid.UUID | None
    result_id: uuid.UUID | None  # note id (notes) or upload id (upload_summary) once done
    error: str | None
    error_code: str | None
    cached: bool  # True = an identical note from the last 24 h was reused (no AI call)
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


# ---------------------------------------------------------------- diagrams / videos / practice
class DiagramOut(BaseModel):
    id: uuid.UUID
    image_url: str | None
    caption: str
    ai_generated: bool
    order: int


class DiagramList(BaseModel):
    items: list[DiagramOut]
    total: int


class VideoOut(BaseModel):
    id: uuid.UUID
    title: str
    url: str
    thumbnail_url: str | None
    duration_seconds: int | None
    channel: str | None
    order: int


class VideoList(BaseModel):
    items: list[VideoOut]
    total: int


class PracticeSummaryOut(BaseModel):
    question_count: int  # answers given on this topic's questions
    accuracy_percent: int  # over all those answers
    last_attempt_at: datetime | None


# ---------------------------------------------------------------- progress
class ProgressEvent(BaseModel):
    event: Literal["opened", "read"]
    seconds: int = Field(default=0, ge=0, le=4 * 60 * 60)  # time since the last event
    completed: bool = False  # finished reading -> progress_percent 100
    # Optional: how far the student scrolled (0-100). Progress never goes down.
    progress_percent: int | None = Field(default=None, ge=0, le=100)


class ProgressOut(BaseModel):
    topic_id: uuid.UUID
    status: TopicProgressStatus
    progress_percent: int
    seconds_spent: int
    last_opened_at: datetime | None
    mastery: MasteryOut


# ---------------------------------------------------------------- bookmarks / search
class BookmarkOut(BaseModel):
    topic: TopicRef
    unit: UnitRef
    created_at: datetime


class BookmarkList(BaseModel):
    items: list[BookmarkOut]
    total: int


class BookmarkState(BaseModel):
    topic_id: uuid.UUID
    is_bookmarked: bool


class SearchTopicOut(TopicRef):
    unit: UnitRef


class SearchOut(BaseModel):
    units: list[UnitRef]
    topics: list[SearchTopicOut]


# ---------------------------------------------------------------- uploads
class UploadAccepted(BaseModel):
    upload_id: uuid.UUID
    job_id: uuid.UUID
    status: LearnJobStatus


class UploadOut(BaseModel):
    id: uuid.UUID
    file_name: str
    mime_type: str | None
    size_bytes: int | None
    topic_id: uuid.UUID | None
    status: LearnJobStatus
    summary_length: SummaryLength | None
    summary: str | None
    key_points: list[str]
    error: str | None
    created_at: datetime


class UploadDetailOut(UploadOut):
    extracted_text: str | None


class UploadPage(BaseModel):
    items: list[UploadOut]
    total: int
    page: int
    size: int


class SaveToNotesRequest(BaseModel):
    # Needed only when the upload has no topic (UUID or code, e.g. "bio-6.1").
    topic_id: str | None = None
