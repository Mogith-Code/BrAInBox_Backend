"""Business logic for the performance module. Owner: Keshomigha.

Topic insights: topic-wise MCQ scores, weak topics and feedback, built only from the
student's own stored answers. Thresholds come from `grading.py` (the single source).

Unit mastery is stored as a history (one row per measurement), so we can show both the
current level and the change over the last week. Study activity drives the streak.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clock
from api.core.errors import ForbiddenError, NotFoundError
from api.core.pagination import Page, PageParams
from api.core.security import CurrentUser
from api.modules.performance import grading, repository
from api.modules.performance.grading import (
    GRADE_BANDS,
    MIN_QUESTIONS_FOR_RELIABLE_RESULT,
    WEAK_STATUSES,
    TopicStatus,
)
from api.modules.performance.repository import AnswerRow, MistakeRow
from api.modules.performance.schemas import (
    AIFeatureUsage,
    AnalyticsAIUsage,
    AnalyticsOverview,
    AnalyticsPerformance,
    CommonMisconception,
    DailyCount,
    GradeBandOut,
    InsightsSummaryResponse,
    MisconceptionOut,
    MissedTopic,
    MistakeOut,
    MistakeUpdate,
    ModuleStatus,
    OverallResult,
    ResourceOut,
    ReviewQuestion,
    TopicFeedback,
    TopicInsightsResponse,
    TopicPerformance,
    TopicStatusCounts,
    UnitAverage,
    UnitInsightsResponse,
    UnitMasteryOut,
    UnitRank,
)
from api.modules.syllabus import service as syllabus_service
from api.modules.syllabus.schemas import UnitOut
from shared.db.models import Mistake, UnitMastery
from shared.enums import MistakeType

MODULE_NAME = "performance"
GENERAL_TOPIC = "General"  # questions not linked to a syllabus topic (same name as exams)
MAX_REVIEW_QUESTIONS = 5
RESOURCES_PER_TOPIC = 3
STREAK_LOOKBACK_DAYS = 400  # long enough for any realistic streak
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


# TODO(Keshomigha): update_mastery


# =========================================================================== unit mastery + streak
# (used by the diagnostic and the home dashboard)


async def record_unit_mastery(
    session: AsyncSession, user_id: uuid.UUID, mastery: dict[uuid.UUID, int], source: str
) -> None:
    """Save a new snapshot (0-100) for each unit. The caller commits."""
    await repository.add_unit_mastery(
        session,
        [
            UnitMastery(user_id=user_id, unit_id=unit_id, mastery=value, source=source)
            for unit_id, value in mastery.items()
        ],
    )


async def current_unit_mastery(session: AsyncSession, user_id: uuid.UUID) -> dict[uuid.UUID, int]:
    """{unit_id: mastery} - newest value per unit. Empty for a new student."""
    return await repository.latest_unit_mastery(session, user_id)


async def unit_mastery_week_ago(session: AsyncSession, user_id: uuid.UUID) -> dict[uuid.UUID, int]:
    """{unit_id: mastery} as it was 7 days ago (newest value older than 7 days)."""
    return await repository.latest_unit_mastery(
        session, user_id, before=clock.now() - timedelta(days=7)
    )


# ---------------------------------------------------------------- GET /insights/units

NOT_ASSESSED_TEXT = "Not assessed yet"
UNIT_NOTE = (
    "Unit mastery (0-100) comes from your newest diagnostic, quiz or exam for each unit. "
    + GRADE_NOTE
)


def _unit_out(unit: UnitOut, latest: UnitMastery | None, week_ago: int | None) -> UnitMasteryOut:
    if latest is None:
        return UnitMasteryOut(
            unit_id=unit.id,
            number=unit.number,
            title=unit.title,
            topic_count=unit.topic_count,
            mastery=None,
            grade=None,
            grade_label=None,
            status=TopicStatus.NOT_ATTEMPTED,
            understanding=NOT_ASSESSED_TEXT,
            change_week=None,
            source=None,
            measured_at=None,
        )
    band = grading.grade_for(latest.mastery)
    return UnitMasteryOut(
        unit_id=unit.id,
        number=unit.number,
        title=unit.title,
        topic_count=unit.topic_count,
        mastery=latest.mastery,
        grade=band.grade,
        grade_label=band.label,
        status=band.status,
        understanding=band.understanding,
        # Only compare a unit with ITSELF a week ago; a unit first measured this week has no change.
        change_week=latest.mastery - week_ago if week_ago is not None else None,
        source=latest.source,
        measured_at=latest.created_at,
    )


def build_unit_insights(
    units: list[UnitOut], latest: dict[uuid.UUID, UnitMastery], week_ago: dict[uuid.UUID, int]
) -> UnitInsightsResponse:
    """Pure: one row per current syllabus unit (Unit 1 first). Units without a measurement are
    `not_attempted` with mastery None - never 0 % - and are left out of the average."""
    rows = [_unit_out(u, latest.get(u.id), week_ago.get(u.id)) for u in units]
    ranks = [
        UnitRank(unit_id=u.id, number=u.number, title=u.title, mastery=latest[u.id].mastery)
        for u in units
        if u.id in latest
    ]
    return UnitInsightsResponse(
        units=rows,
        assessed_units=len(ranks),
        total_units=len(rows),
        average_mastery=(round(sum(r.mastery for r in ranks) / len(ranks), 1) if ranks else None),
        # Ties: the lower unit number wins, so the answer doesn't change between requests.
        strongest=max(ranks, key=lambda r: (r.mastery, -r.number)) if ranks else None,
        weakest=min(ranks, key=lambda r: (r.mastery, r.number)) if ranks else None,
        grade_bands=grade_bands_out(),
        note=UNIT_NOTE,
    )


async def get_unit_insights(session: AsyncSession, user: CurrentUser) -> UnitInsightsResponse:
    """GET /insights/units: the logged-in student's mastery per unit."""
    units = await syllabus_service.get_units(session)
    latest = await repository.latest_unit_mastery_rows(session, user.id)
    week_ago = await unit_mastery_week_ago(session, user.id)
    return build_unit_insights(units, latest, week_ago)


# ---------------------------------------------------------------- streak


async def record_study_activity(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Mark today (Sri Lanka date) as a study day. The caller commits."""
    await repository.add_study_day(session, user_id, clock.today())


def count_streak(days: set[date], today: date) -> int:
    """Consecutive study days ending today - or ending yesterday, so the streak isn't
    shown as broken in the morning before the student has studied today."""
    day = today if today in days else today - timedelta(days=1)
    streak = 0
    while day in days:
        streak += 1
        day -= timedelta(days=1)
    return streak


async def get_streak(session: AsyncSession, user_id: uuid.UUID) -> int:
    today = clock.today()
    days = await repository.study_days_since(
        session, user_id, today - timedelta(days=STREAK_LOOKBACK_DAYS)
    )
    return count_streak(days, today)


# =========================================================================== GET /insights/summary
# One number per Insights card. Built from the same pieces as /insights/units and
# /insights/topics, so the overview never disagrees with the detail screens.

SUMMARY_NOTE = (
    "Mastery comes from your newest diagnostic, quiz or exam per unit; MCQ scores from all "
    "your finished attempts. " + GRADE_NOTE
)


def _topic_counts(topics: list[TopicPerformance]) -> TopicStatusCounts:
    counts = TopicStatusCounts()
    for t in topics:
        if t.status != TopicStatus.NOT_ATTEMPTED:
            setattr(counts, t.status.value, getattr(counts, t.status.value) + 1)
    return counts


def build_summary(
    units: UnitInsightsResponse, analysis: TopicAnalysis, study_days: set[date], today: date
) -> InsightsSummaryResponse:
    """Pure: combine unit mastery, MCQ results and study days into the overview."""
    # Each unit is compared only with itself (see build_unit_insights), then averaged.
    changes = [u.change_week for u in units.units if u.change_week is not None]
    week = {today - timedelta(days=n) for n in range(7)}
    return InsightsSummaryResponse(
        overall_mastery=units.average_mastery,
        mastery_change_week=round(sum(changes) / len(changes), 1) if changes else None,
        units_assessed=units.assessed_units,
        total_units=units.total_units,
        strongest_unit=units.strongest,
        weakest_unit=units.weakest,
        mcq=analysis.overall,
        attempts_completed=analysis.attempts_analysed,
        topics=_topic_counts(analysis.topics),
        weak_topics=[t.topic for t in analysis.topics if t.reliable and t.status in WEAK_STATUSES],
        streak_days=count_streak(study_days, today),
        study_days_last_7=len(study_days & week),
        last_study_date=max((d for d in study_days if d <= today), default=None),
        note=SUMMARY_NOTE,
    )


async def get_insights_summary(session: AsyncSession, user: CurrentUser) -> InsightsSummaryResponse:
    """GET /insights/summary: the logged-in student's overview."""
    today = clock.today()
    units = await get_unit_insights(session, user)
    analysis = analyse_answers(await repository.get_mcq_answer_rows(session, user.id))
    study_days = await repository.study_days_since(
        session, user.id, today - timedelta(days=STREAK_LOOKBACK_DAYS)
    )
    return build_summary(units, analysis, study_days, today)


# =========================================================================== mistake journal


def wrong_answers(rows: list[AnswerRow]) -> list[AnswerRow]:
    """The answers that count as mistakes. Unanswered and unreliable answers are not mistakes,
    the same rule as the topic scores."""
    return [r for r in latest_answer_per_question(rows) if is_valid_answer(r) and not r.is_correct]


def build_mistakes(
    user_id: uuid.UUID,
    wrong: list[AnswerRow],
    misconception_concepts: dict[uuid.UUID, uuid.UUID | None],
    main_concepts: dict[uuid.UUID, uuid.UUID],
) -> list[Mistake]:
    """Pure: one Mistake per wrong answer. Choosing an option linked to a misconception is a
    `misconception`; otherwise a `knowledge_gap`. Types such as `careless` can't be told apart
    automatically. The concept is the misconception's, else the one the question tests most."""
    mistakes = []
    for row in wrong:
        concept = misconception_concepts.get(row.misconception_id) if row.misconception_id else None
        mistakes.append(
            Mistake(
                user_id=user_id,
                question_id=row.question_id,
                response_id=row.response_id,
                misconception_id=row.misconception_id,
                concept_id=concept or main_concepts.get(row.question_id),
                mistake_type=(
                    MistakeType.MISCONCEPTION if row.misconception_id else MistakeType.KNOWLEDGE_GAP
                ),
            )
        )
    return mistakes


async def record_mistakes(session: AsyncSession, user_id: uuid.UUID, attempt_id: uuid.UUID) -> int:
    """Save the wrong MCQ answers of this student's finished attempt; returns how many were new.

    For exams and quizzes: call it after marking the attempt. The caller commits. Calling it
    twice for an attempt adds nothing, and an attempt that isn't finished has no answers yet."""
    wrong = wrong_answers(await repository.get_mcq_answer_rows(session, user_id, attempt_id))
    already = await repository.recorded_response_ids(session, [r.response_id for r in wrong])
    new = [r for r in wrong if r.response_id not in already]
    if not new:
        return 0
    misconception_ids = list({r.misconception_id for r in new if r.misconception_id})
    misconceptions = await repository.get_misconceptions(session, misconception_ids)
    mistakes = build_mistakes(
        user_id,
        new,
        misconception_concepts={m.id: m.concept_id for m in misconceptions},
        main_concepts=await repository.get_main_concepts(session, [r.question_id for r in new]),
    )
    await repository.add_mistakes(session, mistakes)
    return len(mistakes)


def _mistake_out(row: MistakeRow, correct_answers: dict[uuid.UUID, str]) -> MistakeOut:
    mistake, misconception = row.mistake, row.misconception
    return MistakeOut(
        id=mistake.id,
        question_id=mistake.question_id,
        question=row.question,
        your_answer=row.your_answer,
        correct_answer=correct_answers.get(mistake.question_id) if mistake.question_id else None,
        explanation=row.explanation,
        mistake_type=mistake.mistake_type,
        misconception=MisconceptionOut.model_validate(misconception) if misconception else None,
        correction=misconception.correction_md if misconception else None,
        topic_id=row.topic_id,
        topic=row.topic,
        topic_number=row.topic_number,
        unit_id=row.unit_id,
        unit_number=row.unit_number,
        unit=row.unit,
        source=row.source,
        is_resolved=mistake.resolved_at is not None,
        resolved_at=mistake.resolved_at,
        created_at=mistake.created_at,
    )


async def list_mistakes(
    session: AsyncSession,
    user: CurrentUser,
    paging: PageParams,
    *,
    mistake_type: MistakeType | None = None,
    unit_id: uuid.UUID | None = None,
    resolved: bool | None = None,
) -> Page[MistakeOut]:
    """GET /mistakes: the logged-in student's mistakes, newest first."""
    rows, total = await repository.list_mistakes(
        session,
        user.id,
        mistake_type=mistake_type,
        unit_id=unit_id,
        resolved=resolved,
        offset=paging.offset,
        limit=paging.size,
    )
    question_ids = list({r.mistake.question_id for r in rows if r.mistake.question_id})
    correct = await repository.get_correct_answers(session, question_ids)
    return Page.create([_mistake_out(r, correct) for r in rows], total, paging)


async def update_mistake(
    session: AsyncSession, user: CurrentUser, mistake_id: uuid.UUID, req: MistakeUpdate
) -> MistakeOut:
    """PATCH /mistakes/{id}: the "Fixed" toggle. Someone else's mistake is simply "not found"."""
    row = await repository.get_mistake_row(session, user.id, mistake_id)
    if row is None:
        raise NotFoundError("Mistake not found", code="MISTAKE_NOT_FOUND")
    mistake = row.mistake
    if req.resolved and mistake.resolved_at is None:  # keep the first date if tapped twice
        mistake.resolved_at = clock.now()
    elif not req.resolved:
        mistake.resolved_at = None
    await session.commit()
    question_ids = [mistake.question_id] if mistake.question_id else []
    return _mistake_out(row, await repository.get_correct_answers(session, question_ids))


# =========================================================================== admin analytics
# Used by admin/analytics_admin.py. Totals over all students, never one student's data.
# A period of `days` days ends today (Sri Lanka date) and includes today.

MOST_MISSED_LIMIT = 10
MISCONCEPTIONS_LIMIT = 10


def period_start(today: date, days: int) -> date:
    return today - timedelta(days=days - 1)


def _start_of_day(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=clock.SRI_LANKA)


def fill_days(counts: dict[date, int], first_day: date, last_day: date) -> list[DailyCount]:
    """Pure: one entry per day, oldest first. Days without data are 0, so a chart has no gaps."""
    total_days = (last_day - first_day).days + 1
    days = [first_day + timedelta(days=n) for n in range(total_days)]
    return [DailyCount(day=d, count=counts.get(d, 0)) for d in days]


def change_percent(current: int, previous: int) -> float | None:
    """Pure: the change against the previous period; None when it had nothing to compare with."""
    return round(100 * (current - previous) / previous, 1) if previous else None


def feature_usage(by_feature: dict[str, int]) -> list[AIFeatureUsage]:
    """Pure: most used first, with each feature's share of all requests."""
    total = sum(by_feature.values())
    ranked = sorted(by_feature.items(), key=lambda item: (-item[1], item[0]))
    return [
        AIFeatureUsage(feature=name, requests=count, percent=round(100 * count / total, 1))
        for name, count in ranked
    ]


def build_unit_averages(
    units: list[UnitOut], averages: dict[uuid.UUID, tuple[float, int]]
) -> list[UnitAverage]:
    """Pure: one row per current unit. A unit nobody has been measured in is None, never 0 %."""
    rows = []
    for unit in units:
        average, students = averages.get(unit.id, (None, 0))
        rows.append(
            UnitAverage(
                unit_id=unit.id,
                number=unit.number,
                title=unit.title,
                average_mastery=round(average, 1) if average is not None else None,
                students_assessed=students,
            )
        )
    return rows


async def analytics_overview(session: AsyncSession, days: int) -> AnalyticsOverview:
    """GET /admin/analytics/overview"""
    today = clock.today()
    first_day = period_start(today, days)
    since = _start_of_day(first_day)
    active = await repository.count_active_students(session, first_day, today)
    previous = await repository.count_active_students(
        session, first_day - timedelta(days=days), first_day - timedelta(days=1)
    )
    daily = await repository.daily_active_students(session, first_day)
    return AnalyticsOverview(
        days=days,
        since=first_day,
        total_students=await repository.count_students(session),
        new_students=await repository.count_students(session, joined_since=since),
        active_students=active,
        active_students_previous=previous,
        active_change_percent=change_percent(active, previous),
        attempts_completed=await repository.count_finished_attempts(session, since),
        mcq_answers=await repository.count_mcq_answers(session, since),
        daily_active_students=fill_days(daily, first_day, today),
    )


async def analytics_performance(session: AsyncSession, days: int) -> AnalyticsPerformance:
    """GET /admin/analytics/performance. Read from the stored answers, so it doesn't depend on
    mistakes having been recorded."""
    first_day = period_start(clock.today(), days)
    since = _start_of_day(first_day)
    units = await syllabus_service.get_units(session)
    missed = await repository.most_missed_topics(
        session, since, MIN_QUESTIONS_FOR_RELIABLE_RESULT, MOST_MISSED_LIMIT
    )
    misconceptions = await repository.common_misconceptions(session, since, MISCONCEPTIONS_LIMIT)
    return AnalyticsPerformance(
        days=days,
        since=first_day,
        units=build_unit_averages(units, await repository.unit_mastery_averages(session)),
        min_answers_per_topic=MIN_QUESTIONS_FOR_RELIABLE_RESULT,
        most_missed_topics=[
            MissedTopic(
                topic_id=row.topic_id,
                topic=row.topic,
                topic_number=row.topic_number,
                unit_number=row.unit_number,
                unit=row.unit,
                answers=row.answers,
                wrong=row.wrong,
                wrong_percent=round(100 * row.wrong / row.answers, 1),
            )
            for row in missed
        ],
        misconceptions=[
            CommonMisconception(
                misconception_id=row.misconception_id,
                title=row.title,
                times_chosen=row.times_chosen,
                students=row.students,
            )
            for row in misconceptions
        ],
    )


async def analytics_ai_usage(session: AsyncSession, days: int) -> AnalyticsAIUsage:
    """GET /admin/analytics/ai-usage. Cost and tokens stay None until they are recorded."""
    today = clock.today()
    first_day = period_start(today, days)
    since = _start_of_day(first_day)
    totals = await repository.ai_usage_totals(session, since)
    daily = await repository.daily_ai_requests(session, since)
    return AnalyticsAIUsage(
        days=days,
        since=first_day,
        total_requests=totals.requests,
        images=totals.images,
        total_cost_usd=float(totals.cost_usd) if totals.cost_usd is not None else None,
        input_tokens=totals.input_tokens,
        output_tokens=totals.output_tokens,
        by_feature=feature_usage(await repository.ai_usage_by_feature(session, since)),
        daily_requests=fill_days(daily, first_day, today),
    )
