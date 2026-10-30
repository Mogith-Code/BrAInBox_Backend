"""All SQL queries for the recommendations module. Owner: Udith.

Tables: resources, recommendations, study_plans, plan_items, daily_plan_items
Only this module's `service.py` may import this file.
"""

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import DailyPlanItem, Recommendation


async def count_resources(session: AsyncSession) -> int:
    """Example query showing the pattern (replace with real queries)."""
    result = await session.execute(select(func.count()).select_from(Recommendation))
    return result.scalar_one()


async def daily_plan_items(
    session: AsyncSession, user_id: uuid.UUID, day: date
) -> list[DailyPlanItem]:
    result = await session.execute(
        select(DailyPlanItem)
        .where(DailyPlanItem.user_id == user_id, DailyPlanItem.plan_date == day)
        .order_by(DailyPlanItem.position)
    )
    return list(result.scalars())


async def add_daily_plan_items(session: AsyncSession, items: list[DailyPlanItem]) -> None:
    session.add_all(items)
    await session.flush()


async def get_daily_plan_item(session: AsyncSession, item_id: uuid.UUID) -> DailyPlanItem | None:
    return await session.get(DailyPlanItem, item_id)


# TODO(Udith): add the queries this module needs, one small async function each, e.g.
#   async def get_by_id(session: AsyncSession, id: uuid.UUID) -> Recommendation | None:
#       return await session.get(Recommendation, id)
