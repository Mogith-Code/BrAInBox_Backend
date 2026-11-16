"""All SQL queries for the recommendations module.

Tables: resources, recommendations, study_plans, plan_items, daily_plan_items
Only this module's `service.py` may import this file.
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import DailyPlanItem, PlanItem, Recommendation, Resource, StudyPlan
from shared.enums import ContentStatus, RecommendationStatus, StudyPlanStatus

OPEN_STATUSES = (RecommendationStatus.PENDING, RecommendationStatus.IN_PROGRESS)


async def count_resources(session: AsyncSession) -> int:
    result = await session.execute(select(func.count()).select_from(Recommendation))
    return result.scalar_one()


# --------------------------------------------------------------------------- today's plan (home)
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


# --------------------------------------------------------------------------- recommendations
async def list_recommendations(
    session: AsyncSession, user_id: uuid.UUID, statuses: tuple[RecommendationStatus, ...]
) -> list[Recommendation]:
    result = await session.execute(
        select(Recommendation)
        .where(Recommendation.user_id == user_id, Recommendation.status.in_(statuses))
        .order_by(Recommendation.score.desc(), Recommendation.created_at)
    )
    return list(result.scalars())


async def recent_closed(
    session: AsyncSession, user_id: uuid.UUID, since: datetime
) -> list[Recommendation]:
    """Recommendations the student finished or dismissed since `since` (not suggested again)."""
    result = await session.execute(
        select(Recommendation).where(
            Recommendation.user_id == user_id,
            Recommendation.status.in_((RecommendationStatus.DONE, RecommendationStatus.DISMISSED)),
            Recommendation.updated_at >= since,
        )
    )
    return list(result.scalars())


async def get_recommendation(session: AsyncSession, rec_id: uuid.UUID) -> Recommendation | None:
    return await session.get(Recommendation, rec_id)


async def add_all(session: AsyncSession, rows: list[Any]) -> None:
    session.add_all(rows)
    await session.flush()


async def delete_recommendations(session: AsyncSession, ids: list[uuid.UUID]) -> None:
    if ids:
        await session.execute(delete(Recommendation).where(Recommendation.id.in_(ids)))


# --------------------------------------------------------------------------- resources
async def get_resources(
    session: AsyncSession, resource_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Resource]:
    if not resource_ids:
        return {}
    result = await session.execute(select(Resource).where(Resource.id.in_(resource_ids)))
    return {r.id: r for r in result.scalars()}


async def concept_videos(
    session: AsyncSession, concept_ids: list[uuid.UUID], topic_ids: list[uuid.UUID]
) -> list[Resource]:
    """Usable videos for these concepts or their topics, best first. Videos fetched from
    YouTube are stored as approved only after the ranking kept them."""
    if not concept_ids and not topic_ids:
        return []
    result = await session.execute(
        select(Resource)
        .where(
            Resource.status == ContentStatus.APPROVED,
            Resource.resource_type.in_(("youtube", "video")),
            (Resource.concept_id.in_(concept_ids)) | (Resource.topic_id.in_(topic_ids)),
        )
        .order_by(Resource.quality_score.desc().nulls_last(), Resource.order_index)
    )
    return list(result.scalars())


async def last_fetch(session: AsyncSession, concept_id: uuid.UUID) -> datetime | None:
    """When YouTube was last searched for this concept (None = never)."""
    result = await session.execute(
        select(func.max(Resource.fetched_at)).where(
            Resource.concept_id == concept_id, Resource.provider == "youtube"
        )
    )
    return result.scalar_one_or_none()


async def get_by_external_ids(
    session: AsyncSession, provider: str, external_ids: list[str]
) -> dict[str, Resource]:
    if not external_ids:
        return {}
    result = await session.execute(
        select(Resource).where(
            Resource.provider == provider, Resource.external_id.in_(external_ids)
        )
    )
    return {str(r.external_id): r for r in result.scalars()}


# --------------------------------------------------------------------------- study plan
async def active_plan(session: AsyncSession, user_id: uuid.UUID) -> StudyPlan | None:
    result = await session.execute(
        select(StudyPlan).where(
            StudyPlan.user_id == user_id, StudyPlan.status == StudyPlanStatus.ACTIVE
        )
    )
    return result.scalar_one_or_none()


async def archive_active_plans(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(StudyPlan)
        .where(StudyPlan.user_id == user_id, StudyPlan.status == StudyPlanStatus.ACTIVE)
        .values(status=StudyPlanStatus.ARCHIVED, is_active=False)
    )
    await session.flush()


async def plan_items(session: AsyncSession, plan_id: uuid.UUID) -> list[PlanItem]:
    result = await session.execute(
        select(PlanItem)
        .where(PlanItem.study_plan_id == plan_id)
        .order_by(PlanItem.due_date, PlanItem.order_index, PlanItem.created_at)
    )
    return list(result.scalars())


async def get_plan_item(
    session: AsyncSession, user_id: uuid.UUID, item_id: uuid.UUID
) -> PlanItem | None:
    """One item of this student's plans (None if it is someone else's)."""
    result = await session.execute(
        select(PlanItem)
        .join(StudyPlan, StudyPlan.id == PlanItem.study_plan_id)
        .where(PlanItem.id == item_id, StudyPlan.user_id == user_id)
    )
    return result.scalar_one_or_none()
