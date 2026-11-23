"""Business logic for the Learn tab. Owner: Samni.

Students only ever see and change THEIR OWN notes, uploads, jobs, bookmarks and progress:
another student's row answers 404 (it is not revealed that it exists).

AI work (notes, upload summaries) runs as `ai_jobs` rows in the background (api/core/jobs.py
runner, FastAPI BackgroundTasks) and calls the ai_service; the request never waits for it.
Mastery rules live in mastery.py; SQL lives in repository.py.
"""

import hashlib
import json
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import jobs, storage
from api.core.ai_client import AIClient
from api.core.config import get_settings
from api.core.errors import AppError, NotFoundError
from api.core.security import CurrentUser
from api.modules.learn import mastery, official_notes, repository
from api.modules.learn.mastery import NO_PRACTICE, TopicMastery
from api.modules.learn.schemas import (
    AskIn,
    AskOut,
    BookmarkList,
    BookmarkOut,
    BookmarkState,
    Breadcrumb,
    DiagramList,
    DiagramOut,
    GenerateNotesRequest,
    JobAccepted,
    JobKind,
    JobOut,
    LearnJobStatus,
    MasteryOut,
    NoteOut,
    OfficialBookOut,
    OfficialNotesOut,
    PracticeSummaryOut,
    ProgressEvent,
    ProgressOut,
    SaveToNotesRequest,
    SearchOut,
    SearchTopicOut,
    SubjectList,
    SubjectOut,
    SubjectRef,
    TopicDetailOut,
    TopicRef,
    UnitDetailOut,
    UnitList,
    UnitRef,
    UnitSummaryOut,
    UnitTopicOut,
    UploadAccepted,
    UploadDetailOut,
    UploadOut,
    UploadPage,
    VideoList,
    VideoOut,
)
from api.modules.profiles import service as profiles_service
from api.modules.syllabus.service import parse_ref
from shared.db.models import (
    AIJob,
    Note,
    Subject,
    Summary,
    Topic,
    Unit,
    Upload,
    UserTopicProgress,
)
from shared.db.session import SessionLocal
from shared.enums import (
    ContentSource,
    ContentStatus,
    JobStatus,
    JobType,
    NoteKind,
    SummaryLength,
    TopicProgressStatus,
)
from shared.learn_blocks import BlocksError, parse_blocks, read_minutes, to_markdown

logger = logging.getLogger(__name__)

CACHE_HOURS = 24
STORAGE_PREFIX = "uploads/learn/"  # with a bucket (ai_service learn_upload.py reads the same)
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
# MIME type -> allowed file extensions
ALLOWED_UPLOADS: dict[str, tuple[str, ...]] = {
    "application/pdf": (".pdf",),
    DOCX_MIME: (".docx",),
    "text/plain": (".txt",),
    "image/png": (".png",),
    "image/jpeg": (".jpg", ".jpeg"),
}
_STATUS_OUT: dict[JobStatus, LearnJobStatus] = {
    JobStatus.QUEUED: "queued",
    JobStatus.RUNNING: "running",
    JobStatus.SUCCEEDED: "done",
    JobStatus.FAILED: "failed",
    JobStatus.CANCELLED: "failed",
}
_ERROR_CODE = re.compile(r"^([A-Z][A-Z0-9_]+): (.*)$", re.DOTALL)


def _now() -> datetime:
    return datetime.now(UTC)


# =========================================================================== lookups


def _subject_ref(subject: Subject | None) -> SubjectRef:
    if subject is None:  # units seeded before subjects existed
        return SubjectRef(id=uuid.UUID(int=0), code="unknown", name="Unknown")
    return SubjectRef(id=subject.id, code=subject.code, name=subject.name)


def _unit_ref(unit: Unit) -> UnitRef:
    return UnitRef(id=unit.id, code=unit.code, number=unit.number, title=unit.title)


def _topic_ref(topic: Topic) -> TopicRef:
    return TopicRef(id=topic.id, code=topic.code, number=topic.number, title=topic.title)


async def _topic(session: AsyncSession, ref: str) -> tuple[Topic, Unit, Subject | None]:
    row = await repository.get_topic(session, parse_ref(ref))
    if row is None:
        raise NotFoundError(f"Topic '{ref}' not found", code="TOPIC_NOT_FOUND")
    return row


async def _masteries(
    session: AsyncSession, user: CurrentUser, topics: list[Topic]
) -> tuple[dict[uuid.UUID, UserTopicProgress], dict[uuid.UUID, mastery.PracticeStats]]:
    ids = [t.id for t in topics]
    progress = await repository.progress_rows(session, user.id, ids)
    practice = await repository.practice_stats(session, user.id, ids)
    return progress, practice


def _topic_mastery(
    progress: UserTopicProgress | None, practice: mastery.PracticeStats
) -> TopicMastery:
    return mastery.topic_mastery(practice, progress.progress_percent if progress else 0)


def _topic_status(
    m: TopicMastery, progress: UserTopicProgress | None, practice: mastery.PracticeStats
) -> TopicProgressStatus:
    touched = practice.total > 0 or (
        progress is not None and (progress.last_opened_at is not None or progress.seconds_spent > 0)
    )
    return mastery.topic_status(m, progress.status if progress else None, touched)


def _mastery_out(m: TopicMastery) -> MasteryOut:
    return MasteryOut(mastery_percent=m.mastery_percent, mastery_level=m.level, is_weak=m.is_weak)


# =========================================================================== subjects + units


async def list_subjects(session: AsyncSession) -> SubjectList:
    rows = await repository.list_subjects(session)
    items = [
        SubjectOut(
            id=s.id,
            code=s.code,
            name=s.name,
            level=s.level,
            available=s.available,
            syllabus_version=s.syllabus_version,
            unit_count=count,
        )
        for s, count in rows
    ]
    return SubjectList(items=items, total=len(items))


def _unit_summary(unit: Unit, topic_count: int, um: mastery.UnitMastery) -> dict[str, Any]:
    return {
        "id": unit.id,
        "code": unit.code,
        "number": unit.number,
        "title": unit.title,
        "icon_key": unit.icon,
        "order": unit.number,
        "topic_count": topic_count,
        "mastery_percent": um.mastery_percent,
        "mastery_level": um.level,
    }


async def list_subject_units(
    session: AsyncSession, user: CurrentUser, subject_ref: str, q: str | None
) -> UnitList:
    subject = await repository.get_subject(session, parse_ref(subject_ref))
    if subject is None:
        raise NotFoundError(f"Subject '{subject_ref}' not found", code="SUBJECT_NOT_FOUND")
    units = await repository.list_units(session, subject.id)
    topics = await repository.list_current_topics(session, [u.id for u in units])
    progress, practice = await _masteries(session, user, topics)

    by_unit: dict[uuid.UUID, list[Topic]] = {u.id: [] for u in units}
    for t in topics:
        by_unit[t.unit_id].append(t)

    needle = (q or "").strip().lower()
    items = []
    for unit in units:
        unit_topics = by_unit[unit.id]
        if (
            needle
            and needle not in unit.title.lower()
            and not any(needle in t.title.lower() for t in unit_topics)
        ):
            continue
        ms = [
            _topic_mastery(progress.get(t.id), practice.get(t.id, NO_PRACTICE)) for t in unit_topics
        ]
        items.append(
            UnitSummaryOut(**_unit_summary(unit, len(unit_topics), mastery.unit_mastery(ms)))
        )
    return UnitList(items=items, total=len(items))


async def get_unit(session: AsyncSession, user: CurrentUser, unit_ref: str) -> UnitDetailOut:
    row = await repository.get_unit(session, parse_ref(unit_ref))
    if row is None:
        raise NotFoundError(f"Unit '{unit_ref}' not found", code="UNIT_NOT_FOUND")
    unit, subject = row
    topics = await repository.list_current_topics(session, [unit.id])
    progress, practice = await _masteries(session, user, topics)

    topic_items, ms = [], []
    for t in topics:
        p, stats = progress.get(t.id), practice.get(t.id, NO_PRACTICE)
        m = _topic_mastery(p, stats)
        ms.append(m)
        topic_items.append(
            UnitTopicOut(
                id=t.id,
                code=t.code,
                number=t.number,
                title=t.title,
                order=t.order_index,
                status=_topic_status(m, p, stats),
                progress_percent=p.progress_percent if p else 0,
                mastery_percent=m.mastery_percent,
                mastery_level=m.level,
                is_weak=m.is_weak,
                is_outdated=t.is_outdated,
            )
        )
    um = mastery.unit_mastery(ms)
    return UnitDetailOut(
        **_unit_summary(unit, len(topics), um),
        subject=_subject_ref(subject),
        mastered_count=um.mastered_count,
        weak_count=um.weak_count,
        topics=topic_items,
    )


# =========================================================================== topics


async def ask_tutor(session: AsyncSession, req: AskIn, ai: AIClient) -> AskOut:
    """POST /learn/ask: an answer from the approved books, with where it came from."""
    payload: dict[str, Any] = {"question": req.question.strip()}
    if req.topic_id:
        topic, unit, _ = await _topic(session, req.topic_id)
        payload |= {"topic_title": topic.title, "unit_id": str(unit.id)}
    result = (await ai.sync("ask-tutor", payload)).get("result", {})
    return AskOut.model_validate(result)


async def get_topic(session: AsyncSession, user: CurrentUser, topic_ref: str) -> TopicDetailOut:
    topic, unit, subject = await _topic(session, topic_ref)
    progress, practice = await _masteries(session, user, [topic])
    p, stats = progress.get(topic.id), practice.get(topic.id, NO_PRACTICE)
    m = _topic_mastery(p, stats)
    note_types = await repository.note_types_available(session, user.id, topic.id)
    return TopicDetailOut(
        id=topic.id,
        code=topic.code,
        number=topic.number,
        title=topic.title,
        description=topic.description,
        order=topic.order_index,
        breadcrumb=Breadcrumb(subject=_subject_ref(subject), unit=_unit_ref(unit)),
        status=_topic_status(m, p, stats),
        progress_percent=p.progress_percent if p else 0,
        seconds_spent=p.seconds_spent if p else 0,
        last_opened_at=p.last_opened_at if p else None,
        mastery=_mastery_out(m),
        is_bookmarked=await repository.is_bookmarked(session, user.id, topic.id),
        syllabus_version=topic.syllabus_version or (subject.syllabus_version if subject else None),
        is_outdated=topic.is_outdated,
        has_full_notes=NoteKind.FULL.value in note_types,
        has_short_notes=NoteKind.SHORT.value in note_types,
    )


def note_out(note: Note) -> NoteOut:
    source = note.source.value if note.source != ContentSource.ADMIN else "manual"
    return NoteOut(
        id=note.id,
        topic_id=note.topic_id,
        type=NoteKind(note.note_type),
        depth=note.depth,
        title=note.title,
        blocks=note.blocks or [],
        read_minutes=note.read_minutes,
        ai_generated=note.source == ContentSource.AI,
        source=source,  # type: ignore[arg-type]
        is_own=note.user_id is not None,
        created_at=note.created_at,
    )


async def get_notes(
    session: AsyncSession, user: CurrentUser, topic_ref: str, note_type: NoteKind
) -> NoteOut:
    topic, _, _ = await _topic(session, topic_ref)
    note = await repository.get_note_for_user(session, user.id, topic.id, note_type.value)
    if note is None or not note.blocks:
        raise NotFoundError(
            f"No {note_type.value} notes for this topic yet", code="NOTES_NOT_FOUND"
        )
    return note_out(note)


async def get_official_notes(session: AsyncSession, topic_ref: str) -> OfficialNotesOut:
    """The real book pages for this topic's unit, and the page to open first.

    The whole unit stays readable, so a topic that is hard to locate never hides any content.
    """
    topic, unit, _ = await _topic(session, topic_ref)
    books: list[OfficialBookOut] = []
    for document in await repository.official_books(session, unit.id):
        path = await run_in_threadpool(official_notes.book_file, document.file_path)
        if path is None:  # the file can't be read on this server
            logger.warning("Official book file is missing: %s", document.id)
            continue
        pages = await run_in_threadpool(official_notes.page_count, path)
        title = official_notes.book_title(document.title)
        books.append(OfficialBookOut(document_id=document.id, title=title, page_count=pages))
    if not books:
        return OfficialNotesOut(
            topic_id=topic.id,
            available=False,
            books=[],
            open_document_id=None,
            open_page=None,
            exact_match=False,
        )

    # Passages come back grouped by book id, so put them in the books' reading order.
    order = {book.document_id: i for i, book in enumerate(books)}
    rows = await repository.book_passages(session, list(order))
    passages = [
        official_notes.Passage(document_id, page, text)
        for document_id, page, text in sorted(rows, key=lambda row: order[row[0]])
    ]
    start = official_notes.find_start_page(topic.title, passages)
    return OfficialNotesOut(
        topic_id=topic.id,
        available=True,
        books=books,
        open_document_id=start.document_id if start else books[0].document_id,
        open_page=start.page if start else 1,
        exact_match=start.exact if start else False,
    )


async def official_note_page(session: AsyncSession, document_id: uuid.UUID, page: int) -> bytes:
    """One page of an approved book as a JPEG. 404 for anything else."""
    document = await repository.official_book(session, document_id)
    path = None
    if document is not None:
        path = await run_in_threadpool(official_notes.book_file, document.file_path)
    if path is None:
        raise NotFoundError("This book is not available", code="OFFICIAL_NOTES_NOT_FOUND")
    if page > await run_in_threadpool(official_notes.page_count, path):
        raise NotFoundError("This page does not exist", code="OFFICIAL_PAGE_NOT_FOUND")
    return await run_in_threadpool(official_notes.render_page, path, page)


def params_hash(req: GenerateNotesRequest, syllabus_version: str | None) -> str:
    data = {
        "type": req.type.value,
        "depth": req.depth.value,
        "include_examples": req.include_examples,
        "include_past_paper_tips": req.include_past_paper_tips,
        "syllabus_version": syllabus_version,
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


async def generate_notes(
    session: AsyncSession,
    user: CurrentUser,
    topic_ref: str,
    req: GenerateNotesRequest,
    ai: AIClient,
    background_tasks: BackgroundTasks,
) -> JobAccepted:
    """202 + job id. Same request in the last 24 h -> the job is done at once with that note."""
    topic, unit, subject = await _topic(session, topic_ref)
    version = topic.syllabus_version or (subject.syllabus_version if subject else None)
    digest = params_hash(req, version)
    params = req.model_dump(mode="json")
    job_type = (
        JobType.GENERATE_SHORT_NOTES if req.type == NoteKind.SHORT else JobType.GENERATE_NOTES
    )

    cached = await repository.find_cached_note(
        session, user.id, topic.id, req.type.value, digest, _now() - timedelta(hours=CACHE_HOURS)
    )
    if cached is not None:
        now = _now()
        job = AIJob(
            job_type=job_type,
            status=JobStatus.SUCCEEDED,
            input={**params, "params_hash": digest, "cached": True},
            result={"cached": True, "note_id": str(cached.id)},
            requested_by=user.id,
            topic_id=topic.id,
            result_id=cached.id,
            started_at=now,
            finished_at=now,
        )
        session.add(job)
        await session.commit()
        return JobAccepted(job_id=job.id, status="done")

    payload = {
        **params,
        "params_hash": digest,
        "subject": subject.name if subject else "Biology",
        "unit_id": str(unit.id),
        "unit_number": unit.number,
        "unit_title": unit.title,
        "topic_number": topic.number,
        "topic_title": topic.title,
        "syllabus_version": version,
    }
    job = AIJob(
        job_type=job_type,
        status=JobStatus.QUEUED,
        input=payload,
        requested_by=user.id,
        topic_id=topic.id,
    )
    session.add(job)
    await session.commit()
    background_tasks.add_task(run_learn_job, job.id, ai)
    return JobAccepted(job_id=job.id, status="queued")


def _split_error(error: str | None) -> tuple[str | None, str | None]:
    """ "CODE: message" (how api/core/jobs.py stores AppErrors) -> (message, code)."""
    if not error:
        return None, None
    match = _ERROR_CODE.match(error)
    if match:
        return match.group(2), match.group(1)
    return "The job failed. Please try again.", "JOB_FAILED"


def job_out(job: AIJob) -> JobOut:
    kind: JobKind = "upload_summary" if job.job_type == JobType.LEARN_UPLOAD_SUMMARY else "notes"
    message, code = _split_error(job.error)
    return JobOut(
        id=job.id,
        kind=kind,
        status=_STATUS_OUT[job.status],
        topic_id=job.topic_id,
        result_id=job.result_id,
        error=message,
        error_code=code,
        cached=bool((job.result or {}).get("cached")),
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


async def get_job(session: AsyncSession, user: CurrentUser, job_id: uuid.UUID) -> JobOut:
    job = await repository.get_learn_job(session, job_id)
    if job is None or job.requested_by != user.id:
        raise NotFoundError("Job not found", code="JOB_NOT_FOUND")
    return job_out(job)


# --------------------------------------------------------------------------- background runner


async def _save_generated_note(session: AsyncSession, job: AIJob) -> None:
    """on_success of a notes job: validate the blocks again and store the student's note."""
    output: dict[str, Any] = (job.result or {}).get("result") or {}
    try:
        blocks = parse_blocks(output.get("blocks") or [])
    except BlocksError as exc:
        raise AppError(f"The AI returned invalid notes ({exc})", code="INVALID_AI_OUTPUT") from exc
    topic = await session.get(Topic, job.topic_id)
    note_type = "short" if job.job_type == JobType.GENERATE_SHORT_NOTES else "full"
    note = Note(
        topic_id=job.topic_id,
        user_id=job.requested_by,
        created_by=job.requested_by,
        title=f"{topic.title if topic else 'Notes'} ({note_type} notes)",
        note_type=note_type,
        body_md=to_markdown(blocks),
        blocks=blocks,
        depth=job.input.get("depth") if note_type == "full" else None,
        read_minutes=read_minutes(blocks),
        params_hash=job.input.get("params_hash"),
        status=ContentStatus.APPROVED,  # private to its owner, nobody reviews it
        source=ContentSource.AI,
        model=output.get("model"),
        prompt_version=output.get("prompt_version"),
        job_id=job.id,
    )
    session.add(note)
    await session.flush()
    job.result_id = note.id


async def _save_upload_summary(session: AsyncSession, job: AIJob) -> None:
    output: dict[str, Any] = (job.result or {}).get("result") or {}
    upload = await session.get(Upload, uuid.UUID(job.input["upload_id"]))
    if upload is None:  # deleted while the job ran
        raise AppError("The upload was deleted", code="UPLOAD_DELETED")
    upload.extracted_text = output.get("extracted_text")
    upload.processing_status = JobStatus.SUCCEEDED
    upload.error = None
    session.add(
        Summary(
            user_id=upload.user_id,
            upload_id=upload.id,
            topic_id=upload.topic_id,
            body_md=output.get("summary") or "",
            key_points=list(output.get("key_points") or []),
            model=output.get("model"),
            prompt_version=output.get("prompt_version"),
            job_id=job.id,
        )
    )
    job.result_id = upload.id


async def run_learn_job(job_id: uuid.UUID, ai: AIClient) -> None:
    """Background task: queued -> running -> done / failed. Uses its own DB session."""
    async with SessionLocal() as session:
        job = await session.get(AIJob, job_id)
        if job is None:
            logger.error("Learn job %s not found", job_id)
            return
        is_upload = job.job_type == JobType.LEARN_UPLOAD_SUMMARY
        if is_upload:
            upload = await session.get(Upload, uuid.UUID(job.input["upload_id"]))
            if upload is not None:
                upload.processing_status = JobStatus.RUNNING

        async def on_success(done: AIJob) -> None:
            if is_upload:
                await _save_upload_summary(session, done)
            else:
                await _save_generated_note(session, done)

        try:
            job = await jobs.run_job_inline(session, job, ai, on_success=on_success)
        except Exception:  # never let a background task die silently
            logger.exception("Learn job %s crashed", job_id)
            await session.rollback()
            job = await session.get(AIJob, job_id)  # type: ignore[assignment]
            if job is None:
                return
            job.status, job.error, job.finished_at = JobStatus.FAILED, "Job crashed", _now()
        if job.status == JobStatus.FAILED and is_upload:
            upload = await session.get(Upload, uuid.UUID(job.input["upload_id"]))
            if upload is not None:
                upload.processing_status = JobStatus.FAILED
                upload.error = job.error
        await session.commit()


# =========================================================================== diagrams / videos


async def list_diagrams(session: AsyncSession, topic_ref: str, base_url: str) -> DiagramList:
    topic, _, _ = await _topic(session, topic_ref)
    items = []
    for v in await repository.list_diagrams(session, topic.id):
        path = v.image_path or ""
        url = path if path.startswith(("http://", "https://")) else None
        if url is None:
            url = await storage.public_image_url(path, base_url)
        items.append(
            DiagramOut(
                id=v.id,
                image_url=url,
                caption=v.alt_text or v.title,
                ai_generated=v.is_ai_generated,
                order=v.order_index,
            )
        )
    return DiagramList(items=items, total=len(items))


async def list_videos(session: AsyncSession, topic_ref: str) -> VideoList:
    topic, _, _ = await _topic(session, topic_ref)
    items = [
        VideoOut(
            id=r.id,
            title=r.title,
            url=r.url,
            thumbnail_url=r.thumbnail_url,
            duration_seconds=r.duration_seconds,
            channel=r.channel,
            order=r.order_index,
        )
        for r in await repository.list_videos(session, topic.id)
    ]
    return VideoList(items=items, total=len(items))


async def practice_summary(
    session: AsyncSession, user: CurrentUser, topic_ref: str
) -> PracticeSummaryOut:
    topic, _, _ = await _topic(session, topic_ref)
    stats = (await repository.practice_stats(session, user.id, [topic.id])).get(
        topic.id, NO_PRACTICE
    )
    return PracticeSummaryOut(
        question_count=stats.total,
        accuracy_percent=round(stats.accuracy),
        last_attempt_at=stats.last_answered_at,
    )


# =========================================================================== progress


async def record_progress(
    session: AsyncSession, user: CurrentUser, topic_ref: str, event: ProgressEvent
) -> ProgressOut:
    topic, _, _ = await _topic(session, topic_ref)
    row = await repository.get_progress_for_update(session, user.id, topic.id)
    now = _now()
    if event.event == "opened":
        row.last_opened_at = now
    row.seconds_spent = (row.seconds_spent or 0) + event.seconds
    if event.completed:
        row.progress_percent = 100
    elif event.progress_percent is not None:
        row.progress_percent = max(row.progress_percent or 0, event.progress_percent)

    stats = (await repository.practice_stats(session, user.id, [topic.id])).get(
        topic.id, NO_PRACTICE
    )
    m = _topic_mastery(row, stats)
    if m.level == "mastered":
        row.status = TopicProgressStatus.MASTERED
        await profiles_service.check_achievements(session, user.id)
    elif row.status == TopicProgressStatus.NOT_STARTED:
        row.status = TopicProgressStatus.IN_PROGRESS  # opened or read -> started
    await session.commit()
    await session.refresh(row)
    return ProgressOut(
        topic_id=topic.id,
        status=_topic_status(m, row, stats),
        progress_percent=row.progress_percent,
        seconds_spent=row.seconds_spent,
        last_opened_at=row.last_opened_at,
        mastery=_mastery_out(m),
    )


# =========================================================================== bookmarks + search


async def list_bookmarks(session: AsyncSession, user: CurrentUser) -> BookmarkList:
    items = [
        BookmarkOut(topic=_topic_ref(t), unit=_unit_ref(u), created_at=b.created_at)
        for b, t, u in await repository.list_bookmarks(session, user.id)
    ]
    return BookmarkList(items=items, total=len(items))


async def set_bookmark(
    session: AsyncSession, user: CurrentUser, topic_ref: str, on: bool
) -> BookmarkState:
    topic, _, _ = await _topic(session, topic_ref)
    if on:
        await repository.add_bookmark(session, user.id, topic.id)
    else:
        await repository.remove_bookmark(session, user.id, topic.id)
    await session.commit()
    return BookmarkState(topic_id=topic.id, is_bookmarked=on)


async def search(session: AsyncSession, q: str) -> SearchOut:
    units, topics = await repository.search(session, q.strip())
    return SearchOut(
        units=[_unit_ref(u) for u in units],
        topics=[SearchTopicOut(**_topic_ref(t).model_dump(), unit=_unit_ref(u)) for t, u in topics],
    )


# =========================================================================== uploads


def sanitize_filename(name: str | None) -> str:
    """A safe display name: no folders, only letters/digits/space/._-, at most 120 characters."""
    base = Path((name or "").replace("\\", "/")).name
    base = re.sub(r"[^A-Za-z0-9 ._-]+", "_", base).strip(" ._") or "upload"
    stem, dot, ext = base.rpartition(".")
    if dot and len(ext) <= 5:
        return f"{stem[: 120 - len(ext) - 1]}.{ext}"
    return base[:120]


def _looks_like(mime: str, data: bytes) -> bool:
    """Check the file content matches its type (a renamed .exe is not a PDF)."""
    if mime == "application/pdf":
        return data.startswith(b"%PDF")
    if mime == DOCX_MIME:
        return data.startswith(b"PK\x03\x04")
    if mime == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if mime == "text/plain":
        try:
            data[:4096].decode("utf-8")
        except UnicodeDecodeError as exc:
            return exc.start > 4090  # a multi-byte character cut at the end is fine
        return b"\x00" not in data[:4096]
    return False


def _write_upload(rel_path: str, data: bytes, content_type: str) -> None:
    """Blocking. No bucket: UPLOAD_DIR/<rel_path>. With a bucket: uploads/learn/<rel_path>."""
    settings = get_settings()
    if storage.uses_local_files():
        root = Path(settings.UPLOAD_DIR).resolve()
        file = (root / rel_path).resolve()
        if not file.is_relative_to(root):
            raise ValueError("Upload path outside UPLOAD_DIR")
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
    else:
        storage.upload_bytes(STORAGE_PREFIX + rel_path, data, content_type)


def _delete_upload_file(rel_path: str) -> None:
    """Blocking, never raises (the DB row is deleted anyway)."""
    try:
        if storage.uses_local_files():
            root = Path(get_settings().UPLOAD_DIR).resolve()
            file = (root / rel_path).resolve()
            if file.is_relative_to(root):
                file.unlink(missing_ok=True)
        else:
            storage._get_bucket().blob(STORAGE_PREFIX + rel_path).delete()
    except Exception:
        logger.exception("Could not delete upload file %s", rel_path)


async def create_upload(
    session: AsyncSession,
    user: CurrentUser,
    file: UploadFile,
    topic_ref: str | None,
    summary_length: SummaryLength,
    ai: AIClient,
    background_tasks: BackgroundTasks,
) -> UploadAccepted:
    settings = get_settings()
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    file_name = sanitize_filename(file.filename)
    mime = (file.content_type or "").split(";")[0].strip().lower()
    extension = Path(file_name).suffix.lower()
    if mime not in ALLOWED_UPLOADS or extension not in ALLOWED_UPLOADS[mime]:
        raise AppError(
            "Only PDF, DOCX, TXT, PNG and JPG files can be uploaded",
            code="UNSUPPORTED_FILE_TYPE",
            status_code=415,
        )
    data = await file.read(max_bytes + 1)  # never read more than the limit
    if len(data) > max_bytes:
        raise AppError(
            f"The file is larger than {settings.MAX_UPLOAD_MB} MB",
            code="FILE_TOO_LARGE",
            status_code=413,
        )
    if not data:
        raise AppError("The file is empty", code="EMPTY_FILE", status_code=422)
    if not _looks_like(mime, data):
        raise AppError(
            "The file content does not match its type",
            code="UNSUPPORTED_FILE_TYPE",
            status_code=415,
        )

    topic = unit = None
    if topic_ref:
        topic, unit, _ = await _topic(session, topic_ref)

    upload_id = uuid.uuid4()
    rel_path = f"{user.id}/{upload_id}{extension}"
    await run_in_threadpool(_write_upload, rel_path, data, mime)

    upload = Upload(
        id=upload_id,
        user_id=user.id,
        topic_id=topic.id if topic else None,
        title=file_name,
        file_name=file_name,
        file_path=rel_path,
        mime_type=mime,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        processing_status=JobStatus.QUEUED,
        summary_length=summary_length.value,
    )
    job = AIJob(
        job_type=JobType.LEARN_UPLOAD_SUMMARY,
        status=JobStatus.QUEUED,
        input={
            "upload_id": str(upload_id),
            "storage_path": rel_path,
            "mime_type": mime,
            "summary_length": summary_length.value,
            "topic_title": topic.title if topic else "",
            "unit_title": unit.title if unit else "",
        },
        requested_by=user.id,
        topic_id=topic.id if topic else None,
    )
    session.add_all([upload, job])
    try:
        await session.commit()
    except Exception:
        await run_in_threadpool(_delete_upload_file, rel_path)
        raise
    background_tasks.add_task(run_learn_job, job.id, ai)
    return UploadAccepted(upload_id=upload_id, job_id=job.id, status="queued")


def _upload_fields(upload: Upload, summary: Summary | None) -> dict[str, Any]:
    message, _ = _split_error(upload.error)
    return {
        "id": upload.id,
        "file_name": upload.file_name,
        "mime_type": upload.mime_type,
        "size_bytes": upload.size_bytes,
        "topic_id": upload.topic_id,
        "status": _STATUS_OUT[upload.processing_status],
        "summary_length": upload.summary_length,
        "summary": summary.body_md if summary else None,
        "key_points": [str(p) for p in (summary.key_points if summary else [])],
        "error": message,
        "created_at": upload.created_at,
    }


async def list_uploads(
    session: AsyncSession, user: CurrentUser, page: int, size: int
) -> UploadPage:
    uploads, total = await repository.list_uploads(session, user.id, (page - 1) * size, size)
    summaries = await repository.summaries_for(session, [u.id for u in uploads])
    return UploadPage(
        items=[UploadOut(**_upload_fields(u, summaries.get(u.id))) for u in uploads],
        total=total,
        page=page,
        size=size,
    )


async def _own_upload(session: AsyncSession, user: CurrentUser, upload_id: uuid.UUID) -> Upload:
    upload = await repository.get_upload(session, upload_id)
    if upload is None or upload.user_id != user.id:
        raise NotFoundError("Upload not found", code="UPLOAD_NOT_FOUND")
    return upload


async def get_upload(
    session: AsyncSession, user: CurrentUser, upload_id: uuid.UUID
) -> UploadDetailOut:
    upload = await _own_upload(session, user, upload_id)
    summary = (await repository.summaries_for(session, [upload.id])).get(upload.id)
    return UploadDetailOut(**_upload_fields(upload, summary), extracted_text=upload.extracted_text)


async def save_upload_to_short_notes(
    session: AsyncSession, user: CurrentUser, upload_id: uuid.UUID, req: SaveToNotesRequest
) -> NoteOut:
    upload = await _own_upload(session, user, upload_id)
    summary = (await repository.summaries_for(session, [upload.id])).get(upload.id)
    if upload.processing_status != JobStatus.SUCCEEDED or summary is None:
        raise AppError("The summary is not ready yet", code="UPLOAD_NOT_READY", status_code=400)
    topic_id = upload.topic_id
    if req.topic_id:
        topic_id = (await _topic(session, req.topic_id))[0].id
    if topic_id is None:
        raise AppError(
            "Choose a topic for these notes (topic_id)", code="TOPIC_REQUIRED", status_code=400
        )
    topic = await session.get(Topic, topic_id)
    raw: list[dict[str, Any]] = [
        {"type": "heading", "text": f"Summary: {upload.file_name}"},
        {"type": "paragraph", "text": summary.body_md},
    ]
    points = [str(p) for p in summary.key_points if str(p).strip()]
    if points:
        raw += [
            {"type": "heading", "text": "Key points"},
            {"type": "bullet_list", "items": points},
        ]
    blocks = parse_blocks(raw)
    note = Note(
        topic_id=topic_id,
        user_id=user.id,
        created_by=user.id,
        title=f"{topic.title if topic else 'Topic'} (from {upload.file_name})"[:200],
        note_type=NoteKind.SHORT.value,
        body_md=to_markdown(blocks),
        blocks=blocks,
        read_minutes=read_minutes(blocks),
        status=ContentStatus.APPROVED,
        source=ContentSource.UPLOAD,
        model=summary.model,
        prompt_version=summary.prompt_version,
    )
    session.add(note)
    await session.commit()
    await session.refresh(note)
    return note_out(note)


async def delete_upload(session: AsyncSession, user: CurrentUser, upload_id: uuid.UUID) -> None:
    upload = await _own_upload(session, user, upload_id)
    path = upload.file_path
    await session.delete(upload)  # summaries cascade
    await session.commit()
    await run_in_threadpool(_delete_upload_file, path)


# =========================================================================== account delete
# Called by the auth module (DELETE /auth/me). The upload rows belong to the content module.


def upload_files_folder(user_id: uuid.UUID) -> str | None:
    """Storage folder with the student's Learn tab upload files (see _write_upload).

    With a bucket: uploads/learn/<user_id>/. Dev without a bucket the files are in
    UPLOAD_DIR/<user_id>/, given relative to LOCAL_STORAGE_DIR (None if UPLOAD_DIR is outside it).
    """
    if not storage.uses_local_files():
        return f"{STORAGE_PREFIX}{user_id}/"
    settings = get_settings()
    upload_root = Path(settings.UPLOAD_DIR).resolve()
    storage_root = Path(settings.LOCAL_STORAGE_DIR).resolve()
    if not upload_root.is_relative_to(storage_root):
        logger.warning("UPLOAD_DIR is outside LOCAL_STORAGE_DIR: Learn files of %s kept", user_id)
        return None
    return f"{upload_root.relative_to(storage_root).as_posix()}/{user_id}/"


async def export_user_data(session: AsyncSession, user_id: uuid.UUID) -> list[dict[str, Any]]:
    """The student's topic bookmarks for the data export (GET /auth/me/export)."""
    return [
        {
            "topic_id": b.topic_id,
            "topic_title": t.title,
            "unit_id": u.id,
            "unit_title": u.title,
            "created_at": b.created_at,
        }
        for b, t, u in await repository.list_bookmarks(session, user_id)
    ]


async def delete_user_data(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    """Delete the student's topic bookmarks (no commit). Returns the Learn upload folder to
    delete from Storage after the commit."""
    await repository.delete_user_bookmarks(session, user_id)
    folder = upload_files_folder(user_id)
    return [folder] if folder else []
