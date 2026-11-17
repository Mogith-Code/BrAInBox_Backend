"""Business logic for the recommendations module. Owner: Udith.

Today: the daily study plan shown on the home screen ("Today's plan").
Later: recommended resources (YouTube etc.) and longer study plans.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service, never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clock
from api.core.ai_client import AIClient
from api.core.errors import AppError, NotFoundError
from api.core.security import CurrentUser
from api.modules.performance import service as performance_service
from api.modules.performance.service import ConceptState
from api.modules.profiles import service as profiles_service
from api.modules.recommendations import repository, youtube_client
from api.modules.recommendations.schemas import (
    ModuleStatus,
    PlanItemOut,
    PlanItemUpdate,
    ReassessmentOutcome,
    RecommendationList,
    RecommendationOut,
    ResourceOut,
    StudyPlanDay,
    StudyPlanItemOut,
    StudyPlanOut,
)
from shared.db.models import (
    DailyPlanItem,
    PlanItem,
    Recommendation,
    Resource,
    StudyPlan,
)
from shared.enums import (
    ContentStatus,
    PlanSource,
    RecommendationAction,
    RecommendationStatus,
    StudyPlanStatus,
)

logger = logging.getLogger(__name__)

MODULE_NAME = "recommendations"

# The 3 daily tasks: (kind, title start, minutes for up to 2 study hours a day)
PLAN_TEMPLATE = [
    ("recap", "Recap", 10),
    ("practice", "Practice: 10 MCQs", 15),
    ("read", "Read short notes", 5),
]
WEEK_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


async def get_status() -> ModuleStatus:
    """Kept for older callers."""
    return ModuleStatus(module=MODULE_NAME, status="ok")


@dataclass
class FocusUnit:
    """A weak unit to plan around (weakest first), with its first current topic if any."""

    unit_id: uuid.UUID
    unit_number: int
    unit_title: str
    topic_id: uuid.UUID | None
    topic_title: str | None


def minutes_scale(hours_per_day: float | None) -> int:
    """Longer study days get longer tasks: up to 2 h -> x1, 4 h -> x2, 6 h -> x3."""
    return max(1, round((hours_per_day or 0) / 2))


def is_study_day(study_days: list[str], day: date) -> bool:
    return WEEK_DAYS[day.weekday()] in study_days


def build_plan_items(
    user_id: uuid.UUID, day: date, focus: list[FocusUnit], hours_per_day: float | None
) -> list[DailyPlanItem]:
    """Task 1 uses the weakest unit, task 2 the next one, task 3 the third (repeating the
    weakest units if there are fewer than 3)."""
    scale = minutes_scale(hours_per_day)
    items = []
    for position, (kind, label, minutes) in enumerate(PLAN_TEMPLATE, start=1):
        unit = focus[(position - 1) % len(focus)]
        subject = unit.topic_title or f"Unit {unit.unit_number} {unit.unit_title}"
        title = f"{label} {subject}" if kind == "practice" else f"{label}: {subject}"
        items.append(
            DailyPlanItem(
                user_id=user_id,
                plan_date=day,
                position=position,
                kind=kind,
                title=title[:200],
                minutes=minutes * scale,
                unit_id=unit.unit_id,
                topic_id=unit.topic_id,
            )
        )
    return items


def _to_out(item: DailyPlanItem, unit_numbers: dict[uuid.UUID, int]) -> PlanItemOut:
    number = unit_numbers.get(item.unit_id) if item.unit_id else None
    return PlanItemOut(
        id=item.id,
        kind=item.kind,
        title=item.title,
        minutes=item.minutes,
        unit_label=f"Unit {number}" if number else None,
        topic_id=item.topic_id,
        done=item.done,
    )


async def get_today_plan(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    study_days: list[str],
    hours_per_day: float | None,
    focus: list[FocusUnit],
    unit_numbers: dict[uuid.UUID, int],
) -> list[PlanItemOut]:
    """Today's 3 tasks. Created on the first request of the day, then read back (so done /
    undone is remembered). Empty on a non-study day or when there are no weak units yet."""
    today = clock.today()
    items = await repository.daily_plan_items(session, user_id, today)
    if not items:
        if not focus or not is_study_day(study_days, today):
            return []
        try:
            await repository.add_daily_plan_items(
                session, build_plan_items(user_id, today, focus, hours_per_day)
            )
            await session.commit()
        except IntegrityError:  # two requests at the same moment: the other one won
            await session.rollback()
        items = await repository.daily_plan_items(session, user_id, today)
    return [_to_out(i, unit_numbers) for i in items]


async def set_plan_item_done(
    session: AsyncSession,
    user_id: uuid.UUID,
    item_id: uuid.UUID,
    done: bool,
    unit_numbers: dict[uuid.UUID, int],
) -> PlanItemOut:
    """Tick / untick a task. The caller records study activity and commits."""
    item = await repository.get_daily_plan_item(session, item_id)
    if item is None or item.user_id != user_id:
        raise NotFoundError("Plan item not found", code="PLAN_ITEM_NOT_FOUND")
    item.done = done
    item.done_at = clock.now() if done else None
    return _to_out(item, unit_numbers)


# =========================================================================== recommendations
# Rule-based, so every card can say why it was given. Nothing here calls an LLM; the only AI
# step is ranking YouTube results by how well they match the concept (embeddings).
#
#   priority = (1 - mastery) x recency_weight x past_paper_weight x (1.5 if recurring misconception)
#
#   mastery < 0.40                         -> short notes + diagram, then a targeted MCQ set
#   recurring misconception                -> the misconception explained + 5 targeted MCQs
#   0.40 <= mastery < 0.65                 -> a targeted MCQ set (10 questions)
#   written answers missing points         -> compare with the model answer and re-attempt
#   last practice > 7 days, mastery >= 0.65 -> a reassessment
#   any weak concept                       -> 1-2 validated YouTube videos

RECURRING_BOOST = 1.5
REASSESS_AFTER_DAYS = 7
REASSESS_FROM = 0.65
MAX_RECOMMENDATIONS = 12
MAX_VIDEO_CONCEPTS = 2  # YouTube is searched for at most this many concepts per request
VIDEOS_PER_CONCEPT = 2
VIDEO_CACHE_DAYS = 7
CLOSED_COOLDOWN_DAYS = 2  # a finished / dismissed step is not suggested again this soon
PLAN_DAYS = 7
MAX_ITEMS_PER_DAY = 4
DEFAULT_MINUTES_PER_DAY = 60

# Estimated minutes of each action (used to fit the study plan into the student's hours).
MINUTES = {
    RecommendationAction.REVISE_NOTE: 15,
    RecommendationAction.PRACTICE_QUIZ: 15,
    RecommendationAction.WATCH_VIDEO: 12,
    RecommendationAction.RETRY_ANSWER: 20,
    RecommendationAction.REASSESS: 10,
    RecommendationAction.VIEW_VISUAL: 5,
}
NO_DATA_HINT = (
    "Take the diagnostic or a quiz first. Your next steps are built from your own answers."
)


def recency_weight(last_practiced_at: datetime | None, now: datetime) -> float:
    """Pure: recent evidence counts more. Within a week 1.0, within a month 0.8, older 0.6."""
    if last_practiced_at is None:
        return 0.6
    days = (now - last_practiced_at).days
    if days <= 7:
        return 1.0
    if days <= 30:
        return 0.8
    return 0.6


def priority_score(state: ConceptState, now: datetime) -> float:
    """Pure: the formula at the top of this section."""
    score = (1 - state.mastery) * recency_weight(state.last_practiced_at, now) * state.exam_weight
    if state.recurring_count:
        score *= RECURRING_BOOST
    return round(score, 4)


@dataclass
class Suggestion:
    """One recommendation before it is saved."""

    action: RecommendationAction
    concept_id: uuid.UUID
    topic_id: uuid.UUID
    title: str
    reason: str
    score: float
    target: dict[str, Any]
    resource_id: uuid.UUID | None = None

    @property
    def key(self) -> tuple[str, uuid.UUID, str]:
        return (self.action.value, self.concept_id, str(self.target.get("kind", "")))


def _percent(mastery: float) -> int:
    return round(mastery * 100)


def suggestions_for(state: ConceptState, now: datetime) -> list[Suggestion]:
    """Pure: the actions the rules give for ONE concept, most useful first."""
    score = priority_score(state, now)
    base = {"concept_id": str(state.concept_id), "topic_id": str(state.topic_id)}
    out: list[Suggestion] = []

    def add(
        action: RecommendationAction, title: str, reason: str, bonus: float, **target: Any
    ) -> None:
        out.append(
            Suggestion(
                action=action,
                concept_id=state.concept_id,
                topic_id=state.topic_id,
                title=title[:200],
                reason=reason,
                # A small bonus keeps the steps of one concept in a sensible order.
                score=round(score + bonus, 4),
                target={**base, "mastery_before": _percent(state.mastery), **target},
            )
        )

    if state.recurring_count:
        add(
            RecommendationAction.PRACTICE_QUIZ,
            f"Fix a repeated mistake: {state.name}",
            f"Because you made the same mistake {state.recurring_count} times in the last "
            f"14 days: “{state.recurring_misconception}”.",
            0.03,
            kind="misconception",
            count=5,
            misconception_id=str(state.recurring_misconception_id),
        )
    if state.mastery < performance_service.WEAK_BELOW:
        missed = (
            f"you missed {state.open_mistakes} question{'s' if state.open_mistakes != 1 else ''} on"
            if state.open_mistakes
            else "your answers show a gap in"
        )
        add(
            RecommendationAction.REVISE_NOTE,
            f"Revise: {state.name}",
            f"Because {missed} “{state.name}” (mastery {_percent(state.mastery)}%). "
            "Read the short notes and look at the diagram first.",
            0.02,
            kind="short_notes",
        )
        add(
            RecommendationAction.PRACTICE_QUIZ,
            f"Practise: {state.name}",
            f"Because “{state.name}” is weak ({_percent(state.mastery)}%). Try 10 targeted "
            "questions after revising.",
            0.0,
            kind="targeted",
            count=10,
        )
    elif state.mastery < performance_service.IMPROVING_BELOW and not state.recurring_count:
        add(
            RecommendationAction.PRACTICE_QUIZ,
            f"Practise: {state.name}",
            f"Because “{state.name}” is improving ({_percent(state.mastery)}%). 10 targeted "
            "questions will make it stick.",
            0.0,
            kind="targeted",
            count=10,
        )
    if state.written_mistakes:
        add(
            RecommendationAction.RETRY_ANSWER,
            f"Rewrite your answer: {state.name}",
            f"Because your written answer on “{state.name}” missed {state.written_mistakes} "
            f"marking point{'s' if state.written_mistakes != 1 else ''}. Compare it with the "
            "model answer and try again.",
            0.01,
            kind="written",
        )
    days_since = (now - state.last_practiced_at).days if state.last_practiced_at else None
    if (
        state.mastery >= REASSESS_FROM
        and days_since is not None
        and days_since > REASSESS_AFTER_DAYS
    ):
        add(
            RecommendationAction.REASSESS,
            f"Check you still know: {state.name}",
            f"Because you last practised “{state.name}” {days_since} days ago. A quick "
            "5-question check keeps it fresh.",
            0.0,
            kind="reassess",
            count=5,
        )
    return out


def build_suggestions(states: list[ConceptState], now: datetime) -> list[Suggestion]:
    """Pure: every concept's suggestions, highest priority first."""
    out = [s for state in states for s in suggestions_for(state, now)]
    return sorted(out, key=lambda s: -s.score)


def priority_band(rank: int, total: int) -> int:
    """Pure: 1 (do first) .. 5 from the position in the list."""
    if total <= 1:
        return 1
    return min(5, 1 + (rank * 5) // total)


# --------------------------------------------------------------------------- videos


async def _fetch_videos(session: AsyncSession, state: ConceptState, ai: AIClient) -> None:
    """Search YouTube for one concept, keep the videos that match it, cache them for 7 days.

    Never raises: without a key, a network or a ranking the student simply gets no video."""
    try:
        found = await youtube_client.search_videos(f"A/L Biology {state.name}")
        if not found:
            return
        response = await ai.sync(
            "rank-resources",
            {
                "concept": state.name,
                "topic": state.topic_title,
                "candidates": [
                    {"id": v["video_id"], "title": v["title"], "description": v["description"]}
                    for v in found
                ],
                "limit": VIDEOS_PER_CONCEPT,
            },
        )
        ranked = response.get("result", {}).get("resources", [])
    except Exception:
        logger.warning("Could not fetch videos for %s", state.name, exc_info=True)
        return
    by_id = {v["video_id"]: v for v in found}
    known = await repository.get_by_external_ids(session, "youtube", [r["id"] for r in ranked])
    now = clock.now()
    new = []
    for rank in ranked:
        video = by_id.get(rank["id"])
        if video is None:
            continue
        row = known.get(rank["id"])
        if row is None:
            row = Resource(
                title=video["title"][:300],
                url=f"https://www.youtube.com/watch?v={video['video_id']}",
                resource_type="youtube",
                provider="youtube",
                external_id=video["video_id"],
                concept_id=state.concept_id,
                topic_id=state.topic_id,
                status=ContentStatus.APPROVED,
            )
            new.append(row)
        row.channel = video["channel"][:200]
        row.duration_seconds = video["duration_seconds"]
        row.thumbnail_url = video["thumbnail_url"]
        row.quality_score = rank["score"]
        row.fetched_at = now
    await repository.add_all(session, new)


async def _video_suggestions(
    session: AsyncSession, weak: list[ConceptState], ai: AIClient | None, now: datetime
) -> list[Suggestion]:
    if not weak:
        return []
    if ai is not None:
        for state in weak[:MAX_VIDEO_CONCEPTS]:
            fetched = await repository.last_fetch(session, state.concept_id)
            if fetched is None or now - fetched > timedelta(days=VIDEO_CACHE_DAYS):
                await _fetch_videos(session, state, ai)
    videos = await repository.concept_videos(
        session, [s.concept_id for s in weak], [s.topic_id for s in weak]
    )
    out = []
    for state in weak:
        mine = [
            v for v in videos if v.concept_id == state.concept_id or v.topic_id == state.topic_id
        ]
        for video in mine[:VIDEOS_PER_CONCEPT]:
            out.append(
                Suggestion(
                    action=RecommendationAction.WATCH_VIDEO,
                    concept_id=state.concept_id,
                    topic_id=state.topic_id,
                    title=f"Watch: {video.title}"[:200],
                    reason=f"Because “{state.name}” is weak ({_percent(state.mastery)}%). "
                    "This short video explains it.",
                    score=round(priority_score(state, now) - 0.01, 4),
                    target={
                        "concept_id": str(state.concept_id),
                        "topic_id": str(state.topic_id),
                        "kind": str(video.id),
                        "url": video.url,
                        "mastery_before": _percent(state.mastery),
                    },
                    resource_id=video.id,
                )
            )
    return out


# --------------------------------------------------------------------------- refresh + read


async def refresh(
    session: AsyncSession, user_id: uuid.UUID, ai: AIClient | None = None
) -> list[Recommendation]:
    """Rebuild the student's open recommendations from their current mastery and mistakes.

    Open ones that still apply keep their id (and an in-progress status); ones that no longer
    apply are removed; finished / dismissed ones are not suggested again for 2 days.
    The caller commits."""
    now = clock.now()
    states = await performance_service.concept_states(session, user_id)
    suggestions = build_suggestions(states, now)
    weak = sorted(
        (s for s in states if s.mastery < performance_service.WEAK_BELOW),
        key=lambda s: -priority_score(s, now),
    )
    suggestions += await _video_suggestions(session, weak, ai, now)
    suggestions.sort(key=lambda s: -s.score)

    closed = await repository.recent_closed(
        session, user_id, now - timedelta(days=CLOSED_COOLDOWN_DAYS)
    )
    blocked = {_rec_key(r) for r in closed}
    wanted: dict[tuple[str, uuid.UUID | None, str], Suggestion] = {}
    for suggestion in suggestions:
        if suggestion.key not in blocked and suggestion.key not in wanted:
            wanted[suggestion.key] = suggestion
        if len(wanted) >= MAX_RECOMMENDATIONS:
            break

    existing = {
        _rec_key(r): r for r in await repository.list_recommendations(session, user_id, OPEN)
    }
    await repository.delete_recommendations(
        session, [r.id for key, r in existing.items() if key not in wanted]
    )
    rows, new = [], []
    for rank, (key, suggestion) in enumerate(wanted.items()):
        row = existing.get(key)
        if row is None:
            row = Recommendation(
                user_id=user_id,
                action_type=suggestion.action,
                concept_id=suggestion.concept_id,
                status=RecommendationStatus.PENDING,
            )
            new.append(row)
        row.topic_id = suggestion.topic_id
        row.resource_id = suggestion.resource_id
        row.target_ref = {**suggestion.target, "title": suggestion.title}
        row.reason = suggestion.reason
        row.score = suggestion.score
        row.priority = priority_band(rank, len(wanted))
        rows.append(row)
    await repository.add_all(session, new)
    return rows


OPEN = (RecommendationStatus.PENDING, RecommendationStatus.IN_PROGRESS)


def _rec_key(rec: Recommendation) -> tuple[str, uuid.UUID | None, str]:
    action = rec.action_type.value if rec.action_type else ""
    return (action, rec.concept_id, str((rec.target_ref or {}).get("kind", "")))


def _minutes(rec: Recommendation) -> int:
    count = (rec.target_ref or {}).get("count")
    if rec.action_type == RecommendationAction.PRACTICE_QUIZ and count:
        return max(5, round(int(count) * 1.5))
    return MINUTES.get(rec.action_type, 10) if rec.action_type else 10


async def _outs(session: AsyncSession, rows: list[Recommendation]) -> list[RecommendationOut]:
    concepts = {
        c.id: c
        for c in await performance_service.concept_briefs(
            session, [r.concept_id for r in rows if r.concept_id]
        )
    }
    resources = await repository.get_resources(
        session, [r.resource_id for r in rows if r.resource_id]
    )
    out = []
    for rec in rows:
        concept = concepts.get(rec.concept_id) if rec.concept_id else None
        resource = resources.get(rec.resource_id) if rec.resource_id else None
        target = dict(rec.target_ref or {})
        out.append(
            RecommendationOut(
                id=rec.id,
                action=rec.action_type.value if rec.action_type else "revise_note",
                title=str(target.pop("title", "") or (concept.name if concept else "Next step")),
                reason=rec.reason or "",
                priority=rec.priority,
                score=rec.score,
                estimated_minutes=_minutes(rec),
                status=rec.status.value,
                concept_id=rec.concept_id,
                concept=concept.name if concept else None,
                topic_id=rec.topic_id,
                topic=concept.topic_title if concept else None,
                unit_number=concept.unit_number if concept else None,
                mastery=target.get("mastery_before"),
                target=target,
                resource=(
                    ResourceOut(
                        id=resource.id,
                        title=resource.title,
                        url=resource.url,
                        channel=resource.channel,
                        thumbnail_url=resource.thumbnail_url,
                        duration_seconds=resource.duration_seconds,
                    )
                    if resource
                    else None
                ),
                created_at=rec.created_at or clock.now(),
            )
        )
    return out


async def list_recommendations(
    session: AsyncSession, user: CurrentUser, ai: AIClient | None = None
) -> RecommendationList:
    """GET /recommendations: refreshed from the student's current data on every request."""
    rows = await refresh(session, user.id, ai)
    await session.commit()
    return RecommendationList(items=await _outs(session, rows), hint=None if rows else NO_DATA_HINT)


async def _own(session: AsyncSession, user: CurrentUser, rec_id: uuid.UUID) -> Recommendation:
    rec = await repository.get_recommendation(session, rec_id)
    if rec is None or rec.user_id != user.id:
        raise NotFoundError("Recommendation not found", code="RECOMMENDATION_NOT_FOUND")
    return rec


async def update_recommendation(
    session: AsyncSession, user: CurrentUser, rec_id: uuid.UUID, status: str
) -> RecommendationOut:
    rec = await _own(session, user, rec_id)
    rec.status = RecommendationStatus(status)
    rec.is_dismissed = status == "dismissed"
    rec.completed_at = clock.now() if status == "done" else None
    if status == "done":
        await performance_service.record_study_activity(session, user.id)
    await session.commit()
    return (await _outs(session, [rec]))[0]


async def outcome(
    session: AsyncSession, user: CurrentUser, rec_id: uuid.UUID
) -> ReassessmentOutcome:
    """Before / after for a recommendation's concept: the mastery when it was suggested
    against the mastery now (after the student did the quiz)."""
    rec = await _own(session, user, rec_id)
    before = (rec.target_ref or {}).get("mastery_before")
    after = name = None
    level = "not_started"
    if rec.concept_id is not None:
        values = await performance_service.concept_mastery_values(
            session, user.id, [rec.concept_id]
        )
        if rec.concept_id in values:
            after = round(values[rec.concept_id] * 100)
            level = performance_service.mastery_level(values[rec.concept_id])
        briefs = await performance_service.concept_briefs(session, [rec.concept_id])
        name = briefs[0].name if briefs else None
    change = after - before if after is not None and before is not None else None
    improved = bool(change and change > 0)
    if change is None:
        message = "Answer a few questions on this concept to see your progress."
    elif improved:
        message = f"Nice work! You went up {change} points on “{name}”."
    elif change == 0:
        message = f"You held steady on “{name}”. One more round will move it."
    else:
        message = f"“{name}” slipped {abs(change)} points. Revise the short notes and try again."
    return ReassessmentOutcome(
        recommendation_id=rec.id,
        concept=name,
        before=before,
        after=after,
        change=change,
        improved=improved,
        level=level,
        message=message,
    )


# =========================================================================== weekly study plan


@dataclass
class PlanSlot:
    """One planned item before it is saved."""

    day: date
    order: int
    rec: Recommendation
    minutes: int


def fit_plan(
    recs: list[Recommendation],
    *,
    start: date,
    study_days: list[str],
    minutes_per_day: int,
    days: int = PLAN_DAYS,
) -> list[PlanSlot]:
    """Pure: put the recommendations (already in priority order) into the student's study days.

    Each day takes items until its minutes or MAX_ITEMS_PER_DAY are used up. An item longer
    than a whole day's time still gets a day of its own, so nothing important is dropped.
    Without chosen study days every day counts."""
    slots: list[PlanSlot] = []
    queue = list(recs)
    for offset in range(days):
        if not queue:
            break
        day = start + timedelta(days=offset)
        if study_days and not is_study_day(study_days, day):
            continue
        used = 0
        order = 0
        remaining = []
        for rec in queue:
            minutes = _minutes(rec)
            fits = used + minutes <= minutes_per_day or order == 0
            if fits and order < MAX_ITEMS_PER_DAY:
                slots.append(PlanSlot(day=day, order=order, rec=rec, minutes=minutes))
                used += minutes
                order += 1
            else:
                remaining.append(rec)
        queue = remaining
    return slots


def _item_out(item: PlanItem, targets: dict[uuid.UUID, dict[str, Any]]) -> StudyPlanItemOut:
    target = dict(targets.get(item.recommendation_id, {})) if item.recommendation_id else {}
    target.pop("title", None)
    return StudyPlanItemOut(
        id=item.id,
        action=item.action_type.value if item.action_type else None,
        title=item.title,
        date=item.due_date,
        estimated_minutes=item.estimated_minutes,
        is_done=item.is_done,
        order=item.order_index,
        concept_id=item.concept_id,
        topic_id=item.topic_id,
        recommendation_id=item.recommendation_id,
        target=target,
    )


async def _plan_out(
    session: AsyncSession, user_id: uuid.UUID, plan: StudyPlan | None
) -> StudyPlanOut:
    if plan is None:
        return StudyPlanOut(
            id=None, title="Your study plan", start_date=None, end_date=None,
            done=0, total=0, days=[], hint=NO_DATA_HINT,
        )  # fmt: skip
    settings = await profiles_service.get_study_settings(session, user_id)
    available = round((settings.hours_per_day or DEFAULT_MINUTES_PER_DAY / 60) * 60)
    items = await repository.plan_items(session, plan.id)
    recs = {
        r.id: dict(r.target_ref or {})
        for r in await repository.list_recommendations(
            session, user_id, tuple(RecommendationStatus)
        )
    }
    days = []
    start = plan.start_date or clock.today()
    end = plan.end_date or start + timedelta(days=PLAN_DAYS - 1)
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        todays = [i for i in items if i.due_date == day]
        days.append(
            StudyPlanDay(
                date=day,
                weekday=WEEK_DAYS[day.weekday()],
                is_study_day=not settings.study_days or is_study_day(settings.study_days, day),
                minutes_planned=sum(i.estimated_minutes or 0 for i in todays),
                minutes_available=available,
                items=[_item_out(i, recs) for i in todays],
            )
        )
    return StudyPlanOut(
        id=plan.id,
        title=plan.title,
        start_date=start,
        end_date=end,
        done=sum(1 for i in items if i.is_done),
        total=len(items),
        days=days,
        hint=None if items else NO_DATA_HINT,
    )


async def regenerate_plan(
    session: AsyncSession, user: CurrentUser, ai: AIClient | None = None
) -> StudyPlanOut:
    """POST /study-plan/regenerate: a new 7-day plan from the current recommendations. The old
    plan is archived (its ticks stay in the history)."""
    recs = [r for r in await refresh(session, user.id, ai) if r.status in OPEN]
    settings = await profiles_service.get_study_settings(session, user.id)
    minutes_per_day = round((settings.hours_per_day or DEFAULT_MINUTES_PER_DAY / 60) * 60)
    today = clock.today()
    slots = fit_plan(
        recs, start=today, study_days=settings.study_days, minutes_per_day=minutes_per_day
    )
    await repository.archive_active_plans(session, user.id)
    plan = StudyPlan(
        user_id=user.id,
        title=f"Week of {today.strftime('%d %b')}",
        start_date=today,
        end_date=today + timedelta(days=PLAN_DAYS - 1),
        status=StudyPlanStatus.ACTIVE,
        generated_from=PlanSource.RECOMMENDATIONS,
    )
    await repository.add_all(session, [plan])
    await repository.add_all(
        session,
        [
            PlanItem(
                study_plan_id=plan.id,
                action_type=slot.rec.action_type,
                topic_id=slot.rec.topic_id,
                concept_id=slot.rec.concept_id,
                resource_id=slot.rec.resource_id,
                recommendation_id=slot.rec.id,
                title=str((slot.rec.target_ref or {}).get("title") or "Study")[:200],
                due_date=slot.day,
                estimated_minutes=slot.minutes,
                order_index=slot.order,
            )
            for slot in slots
        ],
    )
    await session.commit()
    return await _plan_out(session, user.id, plan)


async def get_plan(
    session: AsyncSession, user: CurrentUser, ai: AIClient | None = None
) -> StudyPlanOut:
    """GET /study-plan: the active plan. A new one is made when there is none yet or the old
    one has ended."""
    plan = await repository.active_plan(session, user.id)
    if plan is None or (plan.end_date is not None and plan.end_date < clock.today()):
        return await regenerate_plan(session, user, ai)
    return await _plan_out(session, user.id, plan)


async def update_plan_item(
    session: AsyncSession, user: CurrentUser, item_id: uuid.UUID, req: PlanItemUpdate
) -> StudyPlanItemOut:
    """Tick / untick an item. Ticking also completes its recommendation and counts as study."""
    item = await repository.get_plan_item(session, user.id, item_id)
    if item is None:
        raise NotFoundError("Plan item not found", code="PLAN_ITEM_NOT_FOUND")
    if req.is_done is not None:
        item.is_done = req.is_done
        item.done_at = clock.now() if req.is_done else None
        if item.recommendation_id is not None:
            rec = await repository.get_recommendation(session, item.recommendation_id)
            if rec is not None:
                rec.status = (
                    RecommendationStatus.DONE if req.is_done else RecommendationStatus.PENDING
                )
                rec.completed_at = item.done_at
        if req.is_done:
            await performance_service.record_study_activity(session, user.id)
    await session.commit()
    return _item_out(item, {})


async def reorder_plan(
    session: AsyncSession, user: CurrentUser, item_ids: list[uuid.UUID]
) -> StudyPlanOut:
    """Save the new order of one day's items (the ids must all be the student's and on the
    same day). 422 PLAN_ORDER_INVALID otherwise."""
    items = [await repository.get_plan_item(session, user.id, item_id) for item_id in item_ids]
    if any(i is None for i in items) or len({i.due_date for i in items if i}) != 1:
        raise AppError(
            "Reorder the items of one day at a time.", code="PLAN_ORDER_INVALID", status_code=422
        )
    for order, item in enumerate(items):
        assert item is not None
        item.order_index = order
    await session.commit()
    return await _plan_out(session, user.id, await repository.active_plan(session, user.id))
