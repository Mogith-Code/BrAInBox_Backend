"""Business logic for the performance module. Owner: Keshomigha.

Topic insights: topic-wise MCQ scores, weak topics and feedback, built only from the
student's own stored answers. Thresholds come from `grading.py` (the single source).

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from api.core.errors import ForbiddenError, NotFoundError
from api.core.security import CurrentUser
from api.modules.performance import grading, repository
from api.modules.performance.grading import (
    GRADE_BANDS,
    MIN_QUESTIONS_FOR_RELIABLE_RESULT,
    WEAK_STATUSES,
    TopicStatus,
)
from api.modules.performance.repository import AnswerRow
from api.modules.performance.schemas import (
    GradeBandOut,
    MisconceptionOut,
    ModuleStatus,
    OverallResult,
    ResourceOut,
    ReviewQuestion,
    TopicFeedback,
    TopicInsightsResponse,
    TopicPerformance,
)

MODULE_NAME = "performance"
GENERAL_TOPIC = "General"  # questions not linked to a syllabus topic (same name as exams)
MAX_REVIEW_QUESTIONS = 5
RESOURCES_PER_TOPIC = 3
GRADE_NOTE = (
    "Grades use project-configured A/L-style thresholds. They describe practice performance "
    "on BrAInBox MCQs and are not official examination grades."
)


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


def is_weak_topic_percent(percent: float) -> bool:
    """Shared weak-topic rule for other modules (e.g. exams): grade S or F."""
    return grading.is_weak_percent(percent)


# --------------------------------------------------------------------------- scoring (pure)


def _percent(correct: int, attempted: int) -> float | None:
    return round(100 * correct / attempted, 2) if attempted else None


def latest_answer_per_question(rows: list[AnswerRow]) -> list[AnswerRow]:
    """Keep one response per question per attempt (the latest), so a duplicate submission
    of the same question in one assessment is counted once. Rows must be oldest first."""
    latest: dict[tuple[uuid.UUID, uuid.UUID], AnswerRow] = {}
    for row in rows:
        latest[(row.attempt_id, row.question_id)] = row
    return list(latest.values())


def is_valid_answer(row: AnswerRow) -> bool:
    """A selected option of this very question with a stored marking result."""
    return (
        row.selected_option_id is not None
        and row.is_correct is not None
        and row.option_question_id == row.question_id
    )


@dataclass
class TopicTally:
    topic_id: uuid.UUID | None
    topic: str
    topic_number: str | None
    unit: str | None
    correct: int = 0
    attempted: int = 0
    unanswered: int = 0
    wrong: list[AnswerRow] = field(default_factory=list)


@dataclass
class TopicAnalysis:
    overall: OverallResult
    topics: list[TopicPerformance]  # ranked, lowest score first
    wrong_by_topic: dict[uuid.UUID | None, list[AnswerRow]]
    attempts_analysed: int


def topic_performance(
    tally: TopicTally, min_questions: int = MIN_QUESTIONS_FOR_RELIABLE_RESULT
) -> TopicPerformance:
    percent = _percent(tally.correct, tally.attempted)
    band = grading.grade_for(percent) if percent is not None else None
    if band is None:
        status, understanding = TopicStatus.NOT_ATTEMPTED, "Not attempted yet"
    elif tally.attempted < min_questions:
        status, understanding = TopicStatus.INSUFFICIENT_DATA, "Insufficient data"
    else:
        status, understanding = band.status, band.understanding
    return TopicPerformance(
        topic_id=tally.topic_id,
        topic=tally.topic,
        topic_number=tally.topic_number,
        unit=tally.unit,
        correct=tally.correct,
        attempted=tally.attempted,
        unanswered=tally.unanswered,
        percent=percent,
        grade=band.grade if band else None,
        grade_label=band.label if band else None,
        status=status,
        understanding=understanding,
        reliable=band is not None and tally.attempted >= min_questions,
    )


def _rank_key(t: TopicPerformance) -> tuple[bool, float, str]:
    # Lowest score first; topics without any valid answer go last.
    return (t.percent is None, t.percent or 0.0, t.topic)


def analyse_answers(
    rows: list[AnswerRow], min_questions: int = MIN_QUESTIONS_FOR_RELIABLE_RESULT
) -> TopicAnalysis:
    """Topic Score (%) = correct / valid attempted x 100, per topic and overall."""
    tallies: dict[uuid.UUID | None, TopicTally] = {}
    unanswered = excluded = 0
    answers = latest_answer_per_question(rows)

    for row in answers:
        tally = tallies.get(row.topic_id)
        if tally is None:
            tally = tallies[row.topic_id] = TopicTally(
                topic_id=row.topic_id,
                topic=row.topic or GENERAL_TOPIC,
                topic_number=row.topic_number,
                unit=row.unit,
            )
        if row.selected_option_id is None:
            tally.unanswered += 1
            unanswered += 1
        elif not is_valid_answer(row):
            excluded += 1
        else:
            tally.attempted += 1
            if row.is_correct:
                tally.correct += 1
            else:
                tally.wrong.append(row)

    correct = sum(t.correct for t in tallies.values())
    attempted = sum(t.attempted for t in tallies.values())
    percent = _percent(correct, attempted)
    band = grading.grade_for(percent) if percent is not None else None
    overall = OverallResult(
        correct=correct,
        attempted=attempted,
        unanswered=unanswered,
        excluded=excluded,
        percent=percent,
        grade=band.grade if band else None,
        grade_label=band.label if band else None,
    )
    topics = sorted((topic_performance(t, min_questions) for t in tallies.values()), key=_rank_key)
    return TopicAnalysis(
        overall=overall,
        topics=topics,
        wrong_by_topic={key: t.wrong for key, t in tallies.items()},
        attempts_analysed=len({row.attempt_id for row in answers}),
    )


# --------------------------------------------------------------------------- feedback (pure)

_ACTIONS: dict[TopicStatus, str] = {
    TopicStatus.VERY_WEAK: (
        "You need to strengthen your understanding of {topic}. Review the fundamental concepts "
        "and model answers, then practise additional MCQs from this topic."
    ),
    TopicStatus.WEAK: (
        "Your understanding of {topic} needs improvement. Revise the key concepts, study why "
        "your incorrect answers were wrong, then practise more MCQs from this topic."
    ),
    TopicStatus.DEVELOPING: (
        "You have a developing understanding of {topic}. Review the questions you answered "
        "incorrectly and practise the related concepts."
    ),
    TopicStatus.GOOD: (
        "You have a good understanding of {topic}. Review the questions you missed and try "
        "more challenging questions to reach a distinction."
    ),
    TopicStatus.STRONG: (
        "Excellent performance in {topic}. Continue practising challenging questions to "
        "maintain your understanding."
    ),
    TopicStatus.INSUFFICIENT_DATA: (
        "Practise at least {needed} more MCQ(s) from {topic} so your understanding can be "
        "judged reliably."
    ),
    TopicStatus.NOT_ATTEMPTED: "Attempt some MCQs from {topic} to get feedback on this topic.",
}


def _summary(t: TopicPerformance) -> str:
    if t.percent is None:
        return f"You have not answered any questions in {t.topic} yet."
    result = (
        f"You answered {t.correct} of {t.attempted} question(s) in {t.topic} correctly "
        f"({t.percent:g}%, grade {t.grade} - {t.grade_label})."
    )
    if t.status == TopicStatus.INSUFFICIENT_DATA:
        return result + " That is too few questions to draw a reliable conclusion yet."
    return f"{result} {t.understanding}."


def build_feedback(
    t: TopicPerformance,
    wrong: list[AnswerRow],
    min_questions: int = MIN_QUESTIONS_FOR_RELIABLE_RESULT,
    model_answers: dict[uuid.UUID, str] | None = None,
    misconceptions: dict[uuid.UUID, MisconceptionOut] | None = None,
    resources: list[ResourceOut] | None = None,
) -> TopicFeedback:
    """Feedback for one topic. Only uses the student's real answers and stored content."""
    model_answers = model_answers or {}
    misconceptions = misconceptions or {}

    review: dict[uuid.UUID, ReviewQuestion] = {}
    seen_misconceptions: dict[uuid.UUID, MisconceptionOut] = {}
    for row in wrong:
        if row.question_id not in review and len(review) < MAX_REVIEW_QUESTIONS:
            review[row.question_id] = ReviewQuestion(
                question_id=row.question_id,
                question=row.question,
                model_answer=model_answers.get(row.question_id) or row.question_explanation,
            )
        if row.misconception_id in misconceptions:
            seen_misconceptions[row.misconception_id] = misconceptions[row.misconception_id]

    needed = max(min_questions - t.attempted, 1)
    return TopicFeedback(
        topic_id=t.topic_id,
        topic=t.topic,
        correct=t.correct,
        attempted=t.attempted,
        percent=t.percent,
        grade=t.grade,
        status=t.status,
        summary=_summary(t),
        action=_ACTIONS[t.status].format(topic=t.topic, needed=needed),
        review_questions=list(review.values()),
        misconceptions=list(seen_misconceptions.values()),
        resources=resources or [],
    )


def grade_bands_out() -> list[GradeBandOut]:
    bands: list[GradeBandOut] = []
    upper: float | None = None
    for band in GRADE_BANDS:  # highest first
        bands.append(
            GradeBandOut(
                grade=band.grade, label=band.label, min_percent=band.min_percent, max_percent=upper
            )
        )
        upper = band.min_percent
    return bands


# --------------------------------------------------------------------------- endpoint


async def get_topic_insights(
    session: AsyncSession, user: CurrentUser, attempt_id: uuid.UUID | None = None
) -> TopicInsightsResponse:
    """Topic-wise MCQ performance of the logged-in student (all finished attempts, or one)."""
    if attempt_id is not None:
        attempt = await repository.get_attempt(session, attempt_id)
        if attempt is None:
            raise NotFoundError(f"Attempt '{attempt_id}' not found", code="ATTEMPT_NOT_FOUND")
        if attempt.user_id != user.id:
            raise ForbiddenError("This attempt belongs to another student")

    rows = await repository.get_mcq_answer_rows(session, user.id, attempt_id)
    analysis = analyse_answers(rows)

    # Extra content for the feedback, fetched only for what the student actually got wrong.
    wrong_rows = [r for rows_ in analysis.wrong_by_topic.values() for r in rows_]
    model_answers = await repository.get_model_answers(
        session, list({r.question_id for r in wrong_rows})
    )
    misconception_ids = list({r.misconception_id for r in wrong_rows if r.misconception_id})
    misconceptions = {
        m.id: MisconceptionOut.model_validate(m)
        for m in await repository.get_misconceptions(session, misconception_ids)
    }
    needs_help = [
        t.topic_id
        for t in analysis.topics
        if t.topic_id is not None and t.status not in (TopicStatus.STRONG, TopicStatus.GOOD)
    ]
    resources = await repository.get_topic_resources(session, needs_help, RESOURCES_PER_TOPIC)

    feedback = [
        build_feedback(
            t,
            analysis.wrong_by_topic.get(t.topic_id, []),
            model_answers=model_answers,
            misconceptions=misconceptions,
            resources=[
                ResourceOut.model_validate(r)
                for r in (resources.get(t.topic_id, []) if t.topic_id else [])
            ],
        )
        for t in analysis.topics
    ]
    return TopicInsightsResponse(
        attempt_id=attempt_id,
        attempts_analysed=analysis.attempts_analysed,
        min_questions_per_topic=MIN_QUESTIONS_FOR_RELIABLE_RESULT,
        overall=analysis.overall,
        topics=analysis.topics,
        weak_topics=[t.topic for t in analysis.topics if t.reliable and t.status in WEAK_STATUSES],
        insufficient_data_topics=[
            t.topic for t in analysis.topics if t.status == TopicStatus.INSUFFICIENT_DATA
        ],
        feedback=feedback,
        grade_bands=grade_bands_out(),
        note=GRADE_NOTE,
    )


# TODO(Keshomigha): record_mistake / update_mastery
