"""HTTP endpoints for the Learn tab. Owner: Samni. All under /api/v1/learn and need a login.

    GET    /learn/subjects                          Subjects (Biology available, others soon)
    GET    /learn/subjects/{id}/units?q=            Units + topic_count + my mastery
    GET    /learn/units/{id}                        Unit + ordered topics with my status
    GET    /learn/topics/{id}                       Topic detail, breadcrumb, mastery, flags
    GET    /learn/topics/{id}/notes?type=           My note, else the official one
    POST   /learn/topics/{id}/notes/generate        AI notes job -> 202 {job_id}
    GET    /learn/jobs/{id}                         Job status (owner only)
    GET    /learn/topics/{id}/diagrams              Ordered images
    GET    /learn/topics/{id}/videos                Ordered videos
    GET    /learn/topics/{id}/practice-summary      My answers on this topic
    POST   /learn/topics/{id}/progress              opened / read events
    GET    /learn/bookmarks                         My bookmarks
    POST   /learn/bookmarks/{topic_id}              Add (idempotent)
    DELETE /learn/bookmarks/{topic_id}              Remove (idempotent)
    GET    /learn/search?q=                         Units + topics (min 2 characters)
    POST   /learn/uploads                           File -> 202, summary job
    GET    /learn/uploads                           My uploads (paginated)
    GET    /learn/uploads/{id}                      One upload with summary
    POST   /learn/uploads/{id}/save-to-short-notes  Summary -> my short note
    DELETE /learn/uploads/{id}                      Delete record + file

Ids in paths: the UUID or the public code ("biology", "u6", "bio-6.1").
Errors: {"detail": "...", "code": "...", "error": {"code", "message"}} (api/core/errors.py).
Rule: routers only validate input and call `service`. No SQL here.
"""

import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)

from api.core.ai_client import AIClientDep
from api.core.database import SessionDep
from api.core.pagination import PageParamsDep
from api.core.security import CurrentUserDep
from api.modules.learn import service
from api.modules.learn.schemas import (
    BookmarkList,
    BookmarkState,
    DiagramList,
    GenerateNotesRequest,
    JobAccepted,
    JobOut,
    NoteOut,
    PracticeSummaryOut,
    ProgressEvent,
    ProgressOut,
    SaveToNotesRequest,
    SearchOut,
    SubjectList,
    TopicDetailOut,
    UnitDetailOut,
    UnitList,
    UploadAccepted,
    UploadDetailOut,
    UploadPage,
    VideoList,
)
from shared.enums import NoteKind, SummaryLength

router = APIRouter(prefix="/learn", tags=["Learn"])


# --------------------------------------------------------------------------- syllabus tree
@router.get("/subjects", response_model=SubjectList, summary="Subjects")
async def list_subjects(user: CurrentUserDep, session: SessionDep) -> SubjectList:
    """`available=false` subjects (Chemistry, Physics) are shown as "coming soon"."""
    return await service.list_subjects(session)


@router.get("/subjects/{subject_id}/units", response_model=UnitList, summary="Units of a subject")
async def list_units(
    subject_id: str,
    user: CurrentUserDep,
    session: SessionDep,
    q: Annotated[
        str | None, Query(max_length=100, description="Filter by unit/topic title")
    ] = None,
) -> UnitList:
    """Units in order with `topic_count`, `mastery_percent` and `mastery_level` for me.

    Errors: 401 · 404 `SUBJECT_NOT_FOUND`."""
    return await service.list_subject_units(session, user, subject_id, q)


@router.get("/units/{unit_id}", response_model=UnitDetailOut, summary="Unit with its topics")
async def get_unit(unit_id: str, user: CurrentUserDep, session: SessionDep) -> UnitDetailOut:
    """Ordered topics with my `status`, `progress_percent`, `is_weak`, plus
    `mastered_count`, `weak_count` and `mastery_percent`. Errors: 401 · 404 `UNIT_NOT_FOUND`."""
    return await service.get_unit(session, user, unit_id)


@router.get("/topics/{topic_id}", response_model=TopicDetailOut, summary="Topic detail")
async def get_topic(topic_id: str, user: CurrentUserDep, session: SessionDep) -> TopicDetailOut:
    """Errors: 401 · 404 `TOPIC_NOT_FOUND`."""
    return await service.get_topic(session, user, topic_id)


# --------------------------------------------------------------------------- notes + jobs
@router.get("/topics/{topic_id}/notes", response_model=NoteOut, summary="Notes of a topic")
async def get_notes(
    topic_id: str,
    user: CurrentUserDep,
    session: SessionDep,
    type: Annotated[NoteKind, Query(description="full | short")] = NoteKind.FULL,
) -> NoteOut:
    """My own note of this type if I have one, else the official note.

    Errors: 401 · 404 `TOPIC_NOT_FOUND` / `NOTES_NOT_FOUND` · 422 unknown type."""
    return await service.get_notes(session, user, topic_id, type)


@router.post(
    "/topics/{topic_id}/notes/generate",
    response_model=JobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate AI notes (poll GET /learn/jobs/{job_id})",
)
async def generate_notes(
    topic_id: str,
    req: GenerateNotesRequest,
    user: CurrentUserDep,
    session: SessionDep,
    ai: AIClientDep,
    background_tasks: BackgroundTasks,
) -> JobAccepted:
    """`depth`: quick (~300 words) | standard (~900) | detailed (~1800). Short notes are 8-15
    bullets. The same request within 24 h returns the earlier note (`status` already `done`).
    When the job is `done`, `result_id` is the note id and GET /notes returns it.

    Errors: 401 · 404 `TOPIC_NOT_FOUND` · 422 `VALIDATION_ERROR`."""
    return await service.generate_notes(session, user, topic_id, req, ai, background_tasks)


@router.get("/jobs/{job_id}", response_model=JobOut, summary="Learn job status")
async def get_job(job_id: uuid.UUID, user: CurrentUserDep, session: SessionDep) -> JobOut:
    """`status`: queued → running → done | failed (`error`, `error_code`).
    Errors: 401 · 404 `JOB_NOT_FOUND` (also for another student's job)."""
    return await service.get_job(session, user, job_id)


# --------------------------------------------------------------------------- media + practice
@router.get("/topics/{topic_id}/diagrams", response_model=DiagramList, summary="Diagrams")
async def list_diagrams(
    topic_id: str, request: Request, user: CurrentUserDep, session: SessionDep
) -> DiagramList:
    """Approved images in display order. Errors: 401 · 404 `TOPIC_NOT_FOUND`."""
    return await service.list_diagrams(session, topic_id, str(request.base_url))


@router.get("/topics/{topic_id}/videos", response_model=VideoList, summary="Videos")
async def list_videos(topic_id: str, user: CurrentUserDep, session: SessionDep) -> VideoList:
    """Approved videos in display order. Errors: 401 · 404 `TOPIC_NOT_FOUND`."""
    return await service.list_videos(session, topic_id)


@router.get(
    "/topics/{topic_id}/practice-summary",
    response_model=PracticeSummaryOut,
    summary="My practice on this topic",
)
async def practice_summary(
    topic_id: str, user: CurrentUserDep, session: SessionDep
) -> PracticeSummaryOut:
    """Zeros when I have not practised it. Errors: 401 · 404 `TOPIC_NOT_FOUND`."""
    return await service.practice_summary(session, user, topic_id)


@router.post("/topics/{topic_id}/progress", response_model=ProgressOut, summary="Reading progress")
async def record_progress(
    topic_id: str, event: ProgressEvent, user: CurrentUserDep, session: SessionDep
) -> ProgressOut:
    """`opened` sets `in_progress` if not started and `last_opened_at`. `seconds` is added to
    `seconds_spent`. `completed: true` sets `progress_percent` to 100.
    Errors: 401 · 404 `TOPIC_NOT_FOUND` · 422 `VALIDATION_ERROR`."""
    return await service.record_progress(session, user, topic_id, event)


# --------------------------------------------------------------------------- bookmarks + search
@router.get("/bookmarks", response_model=BookmarkList, summary="My bookmarks")
async def list_bookmarks(user: CurrentUserDep, session: SessionDep) -> BookmarkList:
    return await service.list_bookmarks(session, user)


@router.post("/bookmarks/{topic_id}", response_model=BookmarkState, summary="Bookmark a topic")
async def add_bookmark(topic_id: str, user: CurrentUserDep, session: SessionDep) -> BookmarkState:
    """Idempotent. Errors: 401 · 404 `TOPIC_NOT_FOUND`."""
    return await service.set_bookmark(session, user, topic_id, True)


@router.delete("/bookmarks/{topic_id}", response_model=BookmarkState, summary="Remove a bookmark")
async def remove_bookmark(
    topic_id: str, user: CurrentUserDep, session: SessionDep
) -> BookmarkState:
    """Idempotent. Errors: 401 · 404 `TOPIC_NOT_FOUND`."""
    return await service.set_bookmark(session, user, topic_id, False)


@router.get("/search", response_model=SearchOut, summary="Search units and topics")
async def search(
    user: CurrentUserDep,
    session: SessionDep,
    q: Annotated[str, Query(min_length=2, max_length=100, pattern=r"\S\S")],
) -> SearchOut:
    """Case-insensitive search in unit and topic titles. Errors: 401 · 422 shorter than 2."""
    return await service.search(session, q)


# --------------------------------------------------------------------------- uploads
@router.post(
    "/uploads",
    response_model=UploadAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a file to summarise (poll GET /learn/uploads/{upload_id})",
)
async def create_upload(
    user: CurrentUserDep,
    session: SessionDep,
    ai: AIClientDep,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(description="PDF, DOCX, TXT, PNG or JPG, at most 10 MB")],
    topic_id: Annotated[str | None, Form(description="Topic UUID or code (optional)")] = None,
    summary_length: Annotated[SummaryLength, Form()] = SummaryLength.MEDIUM,
) -> UploadAccepted:
    """multipart/form-data. Images need OCR (Tesseract) on the server, otherwise the job fails
    with `OCR_NOT_AVAILABLE`.

    Errors: 401 · 404 `TOPIC_NOT_FOUND` · 413 `FILE_TOO_LARGE` · 415 `UNSUPPORTED_FILE_TYPE` ·
    422 `EMPTY_FILE` / `VALIDATION_ERROR`."""
    return await service.create_upload(
        session, user, file, topic_id or None, summary_length, ai, background_tasks
    )


@router.get("/uploads", response_model=UploadPage, summary="My uploads")
async def list_uploads(
    user: CurrentUserDep, session: SessionDep, paging: PageParamsDep
) -> UploadPage:
    """Newest first. `?page=1&size=20`."""
    return await service.list_uploads(session, user, paging.page, paging.size)


@router.get("/uploads/{upload_id}", response_model=UploadDetailOut, summary="One upload")
async def get_upload(
    upload_id: uuid.UUID, user: CurrentUserDep, session: SessionDep
) -> UploadDetailOut:
    """`status`: queued → running → done (summary + key_points) | failed (error).
    Errors: 401 · 404 `UPLOAD_NOT_FOUND`."""
    return await service.get_upload(session, user, upload_id)


@router.post(
    "/uploads/{upload_id}/save-to-short-notes",
    response_model=NoteOut,
    status_code=status.HTTP_201_CREATED,
    summary="Save an upload summary as my short notes",
)
async def save_to_short_notes(
    upload_id: uuid.UUID,
    user: CurrentUserDep,
    session: SessionDep,
    req: SaveToNotesRequest | None = None,
) -> NoteOut:
    """Body optional: `{"topic_id": "bio-6.1"}` when the upload has no topic.
    Errors: 400 `UPLOAD_NOT_READY` / `TOPIC_REQUIRED` · 401 · 404 `UPLOAD_NOT_FOUND`."""
    return await service.save_upload_to_short_notes(
        session, user, upload_id, req or SaveToNotesRequest()
    )


@router.delete(
    "/uploads/{upload_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete an upload"
)
async def delete_upload(
    upload_id: uuid.UUID, user: CurrentUserDep, session: SessionDep
) -> Response:
    """Deletes the record, its summary and the stored file. Errors: 401 · 404 `UPLOAD_NOT_FOUND`."""
    await service.delete_upload(session, user, upload_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
