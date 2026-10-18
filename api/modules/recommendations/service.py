"""Business logic for the recommendations module. Owner: Udith.

Today: the daily study plan shown on the home screen ("Today's plan").
Later: recommended resources (YouTube etc.) and longer study plans.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service, never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clock
from api.core.errors import NotFoundError
from api.modules.recommendations import repository
from api.modules.recommendations.schemas import ModuleStatus, PlanItemOut
from shared.db.models import DailyPlanItem

MODULE_NAME = "recommendations"

# The 3 daily tasks: (kind, title start, minutes for up to 2 study hours a day)
PLAN_TEMPLATE = [
    ("recap", "Recap", 10),
    ("practice", "Practice: 10 MCQs", 15),
    ("read", "Read short notes", 5),
]
WEEK_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


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


# TODO(Udith): list_recommendations (weak concepts from performance.service)
# TODO(Udith): search YouTube via youtube_client.py, rank via RANK_RESOURCES job
# TODO(Udith): longer study plans (study_plans / plan_items) CRUD
