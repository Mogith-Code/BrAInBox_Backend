"""The database itself protects the important rules (one small test each).

Every test runs inside a transaction that is rolled back, so nothing is left behind.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from shared.db.models import (
    Attempt,
    Concept,
    ConceptMastery,
    DocumentChunk,
    MCQOption,
    Note,
    Paper,
    Post,
    Question,
    QuestionStats,
    Reply,
    Response,
    SourceDocument,
    StudyPlan,
    Topic,
    Unit,
    User,
    Vote,
)
from shared.enums import AttemptKind, QuestionType, SourceType

pytestmark = pytest.mark.db


# --------------------------------------------------------------------------- helpers


def unique() -> str:
    return uuid.uuid4().hex[:10]


async def make_user(session) -> User:  # type: ignore[no-untyped-def]
    user = User(firebase_uid=f"db-test-{unique()}", email=f"{unique()}@db-test.local")
    session.add(user)
    await session.flush()
    return user


async def make_concept(session) -> Concept:  # type: ignore[no-untyped-def]
    unit = Unit(number=900_000 + uuid.uuid4().int % 99_999, title="DB test unit")
    session.add(unit)
    await session.flush()
    topic = Topic(unit_id=unit.id, number="T.1", title="DB test topic")
    session.add(topic)
    await session.flush()
    concept = Concept(topic_id=topic.id, name="DB test concept")
    session.add(concept)
    await session.flush()
    return concept


async def make_question(session) -> Question:  # type: ignore[no-untyped-def]
    question = Question(question_type=QuestionType.MCQ, stem=f"Test question {unique()}")
    session.add(question)
    await session.flush()
    return question


async def expect_integrity_error(session) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


# --------------------------------------------------------------------------- MCQs


async def test_only_one_correct_option(session):
    question = await make_question(session)
    session.add_all(
        [
            MCQOption(question_id=question.id, label="A", text="one", is_correct=True),
            MCQOption(question_id=question.id, label="B", text="two", is_correct=True),
        ]
    )
    await expect_integrity_error(session)


async def test_option_label_must_be_a_to_e(session):
    question = await make_question(session)
    session.add(MCQOption(question_id=question.id, label="6", text="six"))
    await expect_integrity_error(session)


# --------------------------------------------------------------------------- community


async def test_vote_needs_exactly_one_target(session):
    user = await make_user(session)
    post = Post(author_id=user.id, title="Q", body="?")
    session.add(post)
    await session.flush()
    reply = Reply(post_id=post.id, author_id=user.id, body="!")
    session.add(reply)
    await session.flush()
    session.add(Vote(user_id=user.id, post_id=post.id, reply_id=reply.id, value=1))
    await expect_integrity_error(session)


# --------------------------------------------------------------------------- one-at-a-time rules


async def test_only_one_unfinished_diagnostic_per_student(session):
    user = await make_user(session)
    paper = Paper(title="Diagnostic", paper_type="diagnostic")
    session.add(paper)
    await session.flush()
    for _ in range(2):
        session.add(
            Attempt(
                paper_id=paper.id,
                user_id=user.id,
                kind=AttemptKind.DIAGNOSTIC,
                status="in_progress",
            )
        )
    await expect_integrity_error(session)


async def test_only_one_active_study_plan(session):
    user = await make_user(session)
    session.add_all(
        [StudyPlan(user_id=user.id, title="Plan 1"), StudyPlan(user_id=user.id, title="Plan 2")]
    )
    await expect_integrity_error(session)


# --------------------------------------------------------------------------- delete rules


async def test_deleting_a_user_removes_their_data_but_keeps_their_posts(session):
    user = await make_user(session)
    concept = await make_concept(session)
    question = await make_question(session)
    paper = Paper(title="Quiz")
    session.add(paper)
    await session.flush()
    attempt = Attempt(paper_id=paper.id, user_id=user.id)
    session.add(attempt)
    await session.flush()
    response = Response(attempt_id=attempt.id, question_id=question.id)
    post = Post(author_id=user.id, title="My question", body="...")
    session.add_all(
        [response, post, ConceptMastery(user_id=user.id, concept_id=concept.id, mastery_score=0.5)]
    )
    await session.flush()
    user_id, attempt_id, response_id, post_id = user.id, attempt.id, response.id, post.id

    await session.execute(delete(User).where(User.id == user_id))
    session.expire_all()

    assert await session.scalar(select(Attempt.id).where(Attempt.id == attempt_id)) is None
    assert await session.scalar(select(Response.id).where(Response.id == response_id)) is None
    mastery = select(ConceptMastery.id).where(ConceptMastery.user_id == user_id)
    assert await session.scalar(mastery) is None
    # the post stays, without an author
    assert await session.scalar(select(Post.id).where(Post.id == post_id)) == post_id
    assert await session.scalar(select(Post.author_id).where(Post.id == post_id)) is None


async def test_a_concept_with_a_note_cannot_be_deleted(session):
    concept = await make_concept(session)
    session.add(Note(topic_id=concept.topic_id, concept_id=concept.id, title="N", body_md="..."))
    await session.flush()
    with pytest.raises(IntegrityError):
        await session.execute(delete(Concept).where(Concept.id == concept.id))
    await session.rollback()


# --------------------------------------------------------------------------- generated columns


async def test_question_correct_rate_is_computed(session):
    question = await make_question(session)
    stats = QuestionStats(question_id=question.id, attempts_count=4, correct_count=3)
    session.add(stats)
    await session.flush()
    await session.refresh(stats)
    assert stats.correct_rate == Decimal("0.750")


async def test_chunk_search_vector_is_filled_automatically(session):
    doc = SourceDocument(
        title="DB test doc", source_type=SourceType.SYLLABUS, file_path=f"test/{unique()}.pdf"
    )
    session.add(doc)
    await session.flush()
    chunk = DocumentChunk(
        document_id=doc.id,
        chunk_index=0,
        heading_path="Photosynthesis",
        text="Chlorophyll absorbs light.",
    )
    session.add(chunk)
    await session.flush()
    await session.refresh(chunk)
    assert "chlorophyl" in chunk.tsv  # the English stem of "chlorophyll"
    assert "photosynthesi" in chunk.tsv
