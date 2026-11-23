"""All SQL for the Learn tab. Owner: Samni. Only learn/service.py imports this file.

Tables read: subjects, units, topics, user_topic_progress, notes, visuals, resources, attempts +
responses + questions (practice), topic_bookmarks, uploads + summaries, ai_jobs.
Functions that take a `ref` accept the UUID id or the public code ("biology", "u6", "bio-6.1").
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, and_, case, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.modules.learn.mastery import RECENT_ANSWERS, PracticeStats
from shared.db.models import (
    AIJob,
    Attempt,
    DocumentChunk,
    Note,
    Question,
    Resource,
    Response,
    SourceDocument,
    Subject,
    Summary,
    Topic,
    TopicBookmark,
    Unit,
    Upload,
    UserTopicProgress,
    Visual,
)
from shared.enums import ContentStatus, DocumentStatus, JobType, SourceType

Ref = uuid.UUID | str

LEARN_JOB_TYPES = (
    JobType.GENERATE_NOTES,
    JobType.GENERATE_SHORT_NOTES,
    JobType.LEARN_UPLOAD_SUMMARY,
)


def _match(id_column: Any, code_column: Any, ref: Ref) -> ColumnElement[bool]:
    return id_column == ref if isinstance(ref, uuid.UUID) else code_column == ref  # type: ignore[no-any-return]


def _like(q: str) -> str:
    """ILIKE pattern for a user's search text (% and _ are taken literally)."""
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


# =========================================================================== syllabus tree


async def list_subjects(session: AsyncSession) -> list[tuple[Subject, int]]:
    unit_count = (
        select(func.count(Unit.id))
        .where(Unit.subject_id == Subject.id, Unit.is_outdated.is_(False))
        .scalar_subquery()
    )
    rows = await session.execute(
        select(Subject, unit_count).order_by(Subject.available.desc(), Subject.name)
    )
    return [(s, n) for s, n in rows.all()]


async def get_subject(session: AsyncSession, ref: Ref) -> Subject | None:
    result = await session.execute(select(Subject).where(_match(Subject.id, Subject.code, ref)))
    return result.scalar_one_or_none()


async def list_units(session: AsyncSession, subject_id: uuid.UUID) -> list[Unit]:
    result = await session.execute(
        select(Unit)
        .where(Unit.subject_id == subject_id, Unit.is_outdated.is_(False))
        .order_by(Unit.number)
    )
    return list(result.scalars())


async def list_current_topics(session: AsyncSession, unit_ids: list[uuid.UUID]) -> list[Topic]:
    if not unit_ids:
        return []
    result = await session.execute(
        select(Topic)
        .where(Topic.unit_id.in_(unit_ids), Topic.is_outdated.is_(False))
        .order_by(Topic.order_index, Topic.number)
    )
    return list(result.scalars())


async def get_unit(session: AsyncSession, ref: Ref) -> tuple[Unit, Subject | None] | None:
    row = (
        await session.execute(
            select(Unit, Subject)
            .outerjoin(Subject, Subject.id == Unit.subject_id)
            .where(_match(Unit.id, Unit.code, ref))
        )
    ).first()
    return (row[0], row[1]) if row else None


async def get_topic(session: AsyncSession, ref: Ref) -> tuple[Topic, Unit, Subject | None] | None:
    row = (
        await session.execute(
            select(Topic, Unit, Subject)
            .join(Unit, Unit.id == Topic.unit_id)
            .outerjoin(Subject, Subject.id == Unit.subject_id)
            .where(_match(Topic.id, Topic.code, ref))
        )
    ).first()
    return (row[0], row[1], row[2]) if row else None


async def search(
    session: AsyncSession, q: str, limit: int = 30
) -> tuple[list[Unit], list[tuple[Topic, Unit]]]:
    pattern = _like(q)
    units = await session.execute(
        select(Unit)
        .where(Unit.is_outdated.is_(False), Unit.title.ilike(pattern))
        .order_by(Unit.number)
        .limit(limit)
    )
    topics = await session.execute(
        select(Topic, Unit)
        .join(Unit, Unit.id == Topic.unit_id)
        .where(
            Topic.is_outdated.is_(False),
            or_(Topic.title.ilike(pattern), Topic.number.ilike(pattern)),
        )
        .order_by(Unit.number, Topic.order_index, Topic.number)
        .limit(limit)
    )
    return list(units.scalars()), [(t, u) for t, u in topics.all()]


# =========================================================================== progress + practice


async def progress_rows(
    session: AsyncSession, user_id: uuid.UUID, topic_ids: list[uuid.UUID]
) -> dict[uuid.UUID, UserTopicProgress]:
    if not topic_ids:
        return {}
    result = await session.execute(
        select(UserTopicProgress).where(
            UserTopicProgress.user_id == user_id, UserTopicProgress.topic_id.in_(topic_ids)
        )
    )
    return {p.topic_id: p for p in result.scalars()}


async def get_progress_for_update(
    session: AsyncSession, user_id: uuid.UUID, topic_id: uuid.UUID
) -> UserTopicProgress:
    """The row (created if missing), locked until commit so parallel events add up correctly."""
    await session.execute(
        insert(UserTopicProgress)
        .values(user_id=user_id, topic_id=topic_id, status="not_started", score=0, is_weak=False)
        .on_conflict_do_nothing(constraint="uq_user_topic_progress_user_topic")
    )
    result = await session.execute(
        select(UserTopicProgress)
        .where(UserTopicProgress.user_id == user_id, UserTopicProgress.topic_id == topic_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


async def practice_stats(
    session: AsyncSession, user_id: uuid.UUID, topic_ids: list[uuid.UUID]
) -> dict[uuid.UUID, PracticeStats]:
    """Marked answers per topic: totals + the last RECENT_ANSWERS answers."""
    if not topic_ids:
        return {}
    answered_at = func.coalesce(Response.answered_at, Response.created_at)
    answers = (
        select(
            Question.topic_id.label("topic_id"),
            Response.is_correct.label("is_correct"),
            answered_at.label("answered_at"),
            func.row_number()
            .over(partition_by=Question.topic_id, order_by=answered_at.desc())
            .label("rn"),
        )
        .join(Attempt, Attempt.id == Response.attempt_id)
        .join(Question, Question.id == Response.question_id)
        .where(
            Attempt.user_id == user_id,
            Response.is_correct.is_not(None),
            Question.topic_id.in_(topic_ids),
        )
        .subquery()
    )
    recent = answers.c.rn <= RECENT_ANSWERS
    result = await session.execute(
        select(
            answers.c.topic_id,
            func.count(),
            func.count().filter(answers.c.is_correct.is_(True)),
            func.count().filter(recent),
            func.count().filter(and_(recent, answers.c.is_correct.is_(True))),
            func.max(answers.c.answered_at),
        ).group_by(answers.c.topic_id)
    )
    return {
        topic_id: PracticeStats(total, correct, recent_total, recent_correct, last)
        for topic_id, total, correct, recent_total, recent_correct, last in result.all()
    }


# =========================================================================== notes


def _visible_note(user_id: uuid.UUID) -> ColumnElement[bool]:
    """My own notes, or approved official topic-level notes."""
    return or_(  # type: ignore[no-any-return]
        Note.user_id == user_id,
        and_(
            Note.user_id.is_(None),
            Note.status == ContentStatus.APPROVED,
            Note.concept_id.is_(None),
        ),
    )


async def note_types_available(
    session: AsyncSession, user_id: uuid.UUID, topic_id: uuid.UUID
) -> set[str]:
    result = await session.execute(
        select(Note.note_type).where(Note.topic_id == topic_id, _visible_note(user_id)).distinct()
    )
    return set(result.scalars())


async def get_note_for_user(
    session: AsyncSession, user_id: uuid.UUID, topic_id: uuid.UUID, note_type: str
) -> Note | None:
    """My newest note of this kind, else the official one."""
    result = await session.execute(
        select(Note)
        .where(Note.topic_id == topic_id, Note.note_type == note_type, _visible_note(user_id))
        .order_by(
            case((Note.user_id.is_(None), 1), else_=0),  # my own first
            Note.created_at.desc(),
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def find_cached_note(
    session: AsyncSession,
    user_id: uuid.UUID,
    topic_id: uuid.UUID,
    note_type: str,
    params_hash: str,
    since: datetime,
) -> Note | None:
    result = await session.execute(
        select(Note)
        .where(
            Note.user_id == user_id,
            Note.topic_id == topic_id,
            Note.note_type == note_type,
            Note.params_hash == params_hash,
            Note.created_at >= since,
        )
        .order_by(Note.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


# =========================================================================== official books


async def official_books(session: AsyncSession, unit_id: uuid.UUID) -> list[SourceDocument]:
    """The unit's imported approved books, in reading order (Part 1 before Part 2)."""
    result = await session.execute(
        select(SourceDocument)
        .where(
            SourceDocument.unit_id == unit_id,
            SourceDocument.source_type == SourceType.APPROVED_NOTE,
            SourceDocument.status == DocumentStatus.READY,
        )
        .order_by(SourceDocument.title)
    )
    return list(result.scalars())


async def official_book(session: AsyncSession, document_id: uuid.UUID) -> SourceDocument | None:
    """One approved book that is ready to read."""
    result = await session.execute(
        select(SourceDocument).where(
            SourceDocument.id == document_id,
            SourceDocument.source_type == SourceType.APPROVED_NOTE,
            SourceDocument.status == DocumentStatus.READY,
        )
    )
    return result.scalar_one_or_none()


async def book_passages(
    session: AsyncSession, document_ids: list[uuid.UUID]
) -> list[tuple[uuid.UUID, int, str]]:
    """(document id, page, text) of the books' passages, ordered inside each book."""
    if not document_ids:
        return []
    result = await session.execute(
        select(DocumentChunk.document_id, DocumentChunk.page, DocumentChunk.text)
        .where(DocumentChunk.document_id.in_(document_ids), DocumentChunk.page.is_not(None))
        .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
    )
    return [(row[0], row[1], row[2]) for row in result.all()]


# =========================================================================== diagrams + videos


async def list_diagrams(session: AsyncSession, topic_id: uuid.UUID) -> list[Visual]:
    """Approved images of the topic (approved = official, every student may see them)."""
    result = await session.execute(
        select(Visual)
        .where(
            Visual.topic_id == topic_id,
            Visual.status == ContentStatus.APPROVED,
            Visual.image_path.is_not(None),
        )
        .order_by(Visual.order_index, Visual.created_at)
    )
    return list(result.scalars())


async def list_videos(session: AsyncSession, topic_id: uuid.UUID) -> list[Resource]:
    result = await session.execute(
        select(Resource)
        .where(
            Resource.topic_id == topic_id,
            Resource.status == ContentStatus.APPROVED,
            Resource.resource_type.in_(("video", "youtube")),
        )
        .order_by(Resource.order_index, Resource.created_at)
    )
    return list(result.scalars())


# =========================================================================== bookmarks


async def is_bookmarked(session: AsyncSession, user_id: uuid.UUID, topic_id: uuid.UUID) -> bool:
    result = await session.execute(
        select(TopicBookmark.id).where(
            TopicBookmark.user_id == user_id, TopicBookmark.topic_id == topic_id
        )
    )
    return result.first() is not None


async def add_bookmark(session: AsyncSession, user_id: uuid.UUID, topic_id: uuid.UUID) -> None:
    await session.execute(
        insert(TopicBookmark)
        .values(user_id=user_id, topic_id=topic_id)
        .on_conflict_do_nothing(constraint="uq_topic_bookmarks_user_topic")
    )


async def remove_bookmark(session: AsyncSession, user_id: uuid.UUID, topic_id: uuid.UUID) -> None:
    await session.execute(
        delete(TopicBookmark).where(
            TopicBookmark.user_id == user_id, TopicBookmark.topic_id == topic_id
        )
    )


async def list_bookmarks(
    session: AsyncSession, user_id: uuid.UUID
) -> list[tuple[TopicBookmark, Topic, Unit]]:
    result = await session.execute(
        select(TopicBookmark, Topic, Unit)
        .join(Topic, Topic.id == TopicBookmark.topic_id)
        .join(Unit, Unit.id == Topic.unit_id)
        .where(TopicBookmark.user_id == user_id)
        .order_by(TopicBookmark.created_at.desc())
    )
    return [(b, t, u) for b, t, u in result.all()]


# =========================================================================== uploads + jobs


def _learn_upload() -> ColumnElement[bool]:
    """Uploads made on the Learn tab (the older /uploads/pdf ones have no summary_length)."""
    return Upload.summary_length.is_not(None)  # type: ignore[no-any-return]


async def list_uploads(
    session: AsyncSession, user_id: uuid.UUID, offset: int, limit: int
) -> tuple[list[Upload], int]:
    where = and_(Upload.user_id == user_id, _learn_upload())
    total = (await session.execute(select(func.count()).where(where))).scalar_one()
    result = await session.execute(
        select(Upload)
        .where(where)
        .order_by(Upload.created_at.desc(), Upload.id)
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars()), int(total)


async def get_upload(session: AsyncSession, upload_id: uuid.UUID) -> Upload | None:
    result = await session.execute(select(Upload).where(Upload.id == upload_id, _learn_upload()))
    return result.scalar_one_or_none()


async def summaries_for(
    session: AsyncSession, upload_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Summary]:
    if not upload_ids:
        return {}
    result = await session.execute(
        select(Summary).where(Summary.upload_id.in_(upload_ids)).order_by(Summary.created_at.desc())
    )
    found: dict[uuid.UUID, Summary] = {}
    for summary in result.scalars():
        if summary.upload_id is not None:
            found.setdefault(summary.upload_id, summary)  # newest first
    return found


async def get_learn_job(session: AsyncSession, job_id: uuid.UUID) -> AIJob | None:
    result = await session.execute(
        select(AIJob).where(AIJob.id == job_id, AIJob.job_type.in_(LEARN_JOB_TYPES))
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------- account delete


async def delete_user_bookmarks(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Delete the student's topic bookmarks. No commit."""
    await session.execute(delete(TopicBookmark).where(TopicBookmark.user_id == user_id))
