"""Business logic for the home dashboard. Owner: Samni.

Everything on the home screen comes from other modules' services - simple, explainable
numbers, no fake data:
  * streak            performance  (consecutive study days, Sri Lanka date)
  * days_to_exam      profiles     (exam_year) + setting AL_EXAM_DATES (dates TBD)
  * next_best_action  quizzes (diagnostic done?) + performance (weakest unit) + AI reason
  * todays_plan       recommendations (3 tasks per study day, from the weakest units)
  * overall_mastery   performance  (average unit mastery, change vs 7 days ago)
  * continue_learning syllabus topics of the weakest units

Rules:
  * No SQL here (and no tables of its own).
  * Call other modules' services, never their repositories.
  * AI work goes through `api.core.ai_client`.
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clock
from api.core.ai_client import AIClient
from api.core.config import get_settings
from api.core.errors import AppError
from api.core.security import CurrentUser
from api.modules.home.schemas import (
    ActionTarget,
    ContinueItem,
    HomeSummary,
    NextBestAction,
    TodaysPlan,
)
from api.modules.performance import service as performance_service
from api.modules.profiles import service as profiles_service
from api.modules.quizzes import service as quizzes_service
from api.modules.recommendations import service as recommendations_service
from api.modules.recommendations.schemas import PlanItemOut
from api.modules.recommendations.service import FocusUnit
from api.modules.syllabus import service as syllabus_service

logger = logging.getLogger(__name__)

CONTINUE_LEARNING_LIMIT = 5
PLAN_FOCUS_UNITS = 3

DIAGNOSTIC_ACTION = NextBestAction(
    type="diagnostic",
    title="Find your starting point",
    reason="A quick 10-minute check across all 10 units, so your plan starts where you are.",
    button_label="Start diagnostic",
    minutes=10,
    target=None,
    ai_generated=False,
)


# =========================================================================== small helpers


def greeting_name(user: CurrentUser) -> str:
    """First name ("Nethmi Perera" -> "Nethmi"), else the email name, else "there"."""
    if user.full_name and user.full_name.strip():
        return user.full_name.strip().split()[0]
    if user.email:
        return user.email.split("@")[0]
    return "there"


def initials(user: CurrentUser) -> str:
    """ "Nethmi Perera" -> "NP", "Nethmi" -> "N", no name -> first letter of the email."""
    if user.full_name and user.full_name.strip():
        parts = user.full_name.split()
        return "".join(p[0] for p in parts[:2]).upper()
    return (user.email or "?")[0].upper()


def days_to_exam(exam_year: int | None) -> int | None:
    """Days from today (Sri Lanka) to the A/L exam; null if the year or its date is unknown."""
    if exam_year is None:
        return None
    exam_date = get_settings().AL_EXAM_DATES.get(exam_year)
    if exam_date is None:
        return None
    return max(0, (exam_date - clock.today()).days)


def average(values: list[int]) -> float | None:
    return sum(values) / len(values) if values else None


# =========================================================================== summary


async def _focus_units(
    session: AsyncSession, mastery: dict[uuid.UUID, int]
) -> tuple[list[FocusUnit], dict[uuid.UUID, int], dict[uuid.UUID, list]]:
    """Units with mastery data, weakest first, plus unit numbers and topics per unit."""
    units = {u.id: u for u in await syllabus_service.list_units(session)}
    ranked = sorted(
        (u for u in units.values() if u.id in mastery), key=lambda u: (mastery[u.id], u.number)
    )
    topics = await syllabus_service.list_topics_by_unit(session, [u.id for u in ranked])
    focus = [
        FocusUnit(
            unit_id=u.id,
            unit_number=u.number,
            unit_title=u.title,
            topic_id=topics[u.id][0].id if topics[u.id] else None,
            topic_title=topics[u.id][0].title if topics[u.id] else None,
        )
        for u in ranked
    ]
    return focus, {u.id: u.number for u in units.values()}, topics


async def _revise_action(ai: AIClient, weakest: FocusUnit, mastery: int) -> NextBestAction:
    subject = weakest.topic_title or weakest.unit_title
    reason, ai_generated = (
        f"Unit {weakest.unit_number} ({weakest.unit_title}) is your lowest unit right now "
        f"at {mastery}% mastery. A short revision helps most here.",
        False,
    )
    try:
        response = await ai.sync(
            "next-action",
            {
                "unit_code": str(weakest.unit_number),
                "unit_title": weakest.unit_title,
                "topic_title": weakest.topic_title,
                "mastery": mastery,
            },
        )
        ai_reason = str(response.get("result", {}).get("reason", "")).strip()
        if ai_reason:
            reason, ai_generated = ai_reason, True
    except AppError as exc:
        logger.warning("Next-action reason from AI failed: %s", exc.message)
    # TODO(Samni): cache the AI reason per day instead of asking on every home request.
    return NextBestAction(
        type="revise",
        title=f"Revise: {subject}",
        reason=reason,
        button_label="Start 10-min revision",
        minutes=10,
        target=ActionTarget(unit_code=str(weakest.unit_number), topic_id=weakest.topic_id),
        ai_generated=ai_generated,
    )


async def get_summary(session: AsyncSession, user: CurrentUser, ai: AIClient) -> HomeSummary:
    settings = await profiles_service.get_study_settings(session, user.id)
    mastery = await performance_service.current_unit_mastery(session, user.id)
    week_ago = await performance_service.unit_mastery_week_ago(session, user.id)
    focus, unit_numbers, topics = await _focus_units(session, mastery)
    diagnostic_done = await quizzes_service.has_completed_diagnostic(session, user.id)

    # Next best action: the diagnostic first, then the weakest unit.
    if not diagnostic_done or not focus:
        action = DIAGNOSTIC_ACTION
    else:
        action = await _revise_action(ai, focus[0], mastery[focus[0].unit_id])

    plan_items = await recommendations_service.get_today_plan(
        session,
        user.id,
        study_days=settings.study_days,
        hours_per_day=settings.hours_per_day,
        focus=focus[:PLAN_FOCUS_UNITS],
        unit_numbers=unit_numbers,
    )

    now_avg, then_avg = average(list(mastery.values())), average(list(week_ago.values()))
    change = round(now_avg - then_avg) if now_avg is not None and then_avg is not None else 0

    continue_learning = [
        ContinueItem(
            topic_id=t.id,
            title=t.title,
            unit_code=str(f.unit_number),
            progress=mastery[f.unit_id],
        )
        for f in focus
        for t in topics[f.unit_id]
    ][:CONTINUE_LEARNING_LIMIT]

    return HomeSummary(
        greeting_name=greeting_name(user),
        initials=initials(user),
        streak_days=await performance_service.get_streak(session, user.id),
        days_to_exam=days_to_exam(settings.exam_year),
        next_best_action=action,
        todays_plan=TodaysPlan(
            done=sum(1 for i in plan_items if i.done), total=len(plan_items), items=plan_items
        ),
        overall_mastery=round(now_avg) if now_avg is not None else None,
        mastery_change_week=change,
        continue_learning=continue_learning,
    )


async def set_plan_item(
    session: AsyncSession, user: CurrentUser, item_id: uuid.UUID, done: bool
) -> PlanItemOut:
    """Tick / untick one of today's tasks. Finishing a task counts as study activity."""
    unit_numbers = {u.id: u.number for u in await syllabus_service.list_units(session)}
    item = await recommendations_service.set_plan_item_done(
        session, user.id, item_id, done, unit_numbers
    )
    if done:
        await performance_service.record_study_activity(session, user.id)
    await session.commit()
    return item
