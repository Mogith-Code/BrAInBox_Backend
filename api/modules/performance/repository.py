"""All SQL queries for the performance module. Owner: Keshomigha.

Tables: mistakes, concept_mastery, unit_mastery, study_activity
Only this module's `service.py` may import this file.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import Mistake, StudyActivity, UnitMastery


async def count_mistakes(session: AsyncSession) -> int:
    """Example query showing the pattern."""
    result = await session.execute(select(func.count()).select_from(Mistake))
    return result.scalar_one()


# ---------------------------------------------------------------- unit mastery (history)
async def add_unit_mastery(session: AsyncSession, rows: list[UnitMastery]) -> None:
    session.add_all(rows)
    await session.flush()


async def latest_unit_mastery(
    session: AsyncSession, user_id: uuid.UUID, before: datetime | None = None
) -> dict[uuid.UUID, int]:
    """{unit_id: mastery} from the newest snapshot per unit (optionally only older than `before`)."""
    stmt = (
        select(UnitMastery.unit_id, UnitMastery.mastery)
        .where(UnitMastery.user_id == user_id)
        # Postgres DISTINCT ON: keep the first row per unit = the newest one
        .ext(distinct_on(UnitMastery.unit_id))
        .order_by(UnitMastery.unit_id, UnitMastery.created_at.desc())
    )
    if before is not None:
        stmt = stmt.where(UnitMastery.created_at < before)
    result = await session.execute(stmt)
    return {unit_id: mastery for unit_id, mastery in result.all()}


# ---------------------------------------------------------------- study activity (streak)
async def add_study_day(session: AsyncSession, user_id: uuid.UUID, day: date) -> None:
    """One row per student per day; a second call on the same day does nothing."""
    await session.execute(
        insert(StudyActivity)
        .values(user_id=user_id, activity_date=day)
        .on_conflict_do_nothing(constraint="uq_study_activity_user_date")
    )


async def study_days_since(session: AsyncSession, user_id: uuid.UUID, since: date) -> set[date]:
    result = await session.execute(
        select(StudyActivity.activity_date).where(
            StudyActivity.user_id == user_id, StudyActivity.activity_date >= since
        )
    )
    return set(result.scalars())
