"""Business logic for the performance module. Owner: Keshomigha.

Unit mastery is stored as a history (one row per measurement), so we can show both the
current level and the change over the last week. Study activity drives the streak.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service, never its repository.
"""

import uuid
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from api.core import clock
from api.modules.performance import repository
from api.modules.performance.schemas import ModuleStatus
from shared.db.models import UnitMastery

MODULE_NAME = "performance"
STREAK_LOOKBACK_DAYS = 400  # long enough for any realistic streak


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


# ---------------------------------------------------------------- unit mastery


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


# TODO(Keshomigha): record_mistake / concept mastery / GET /insights/* / GET /mistakes
