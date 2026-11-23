"""All SQL queries for the profiles module. Owner: Mogith.

Tables: student_profiles, user_settings, achievements, user_achievements
Only this module's `service.py` may import this file.
"""

import uuid
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import Achievement, StudentProfile, User, UserAchievement, UserSettings


async def count_student_profiles(session: AsyncSession) -> int:
    """Example query showing the pattern (replace with real queries)."""
    result = await session.execute(select(func.count()).select_from(StudentProfile))
    return result.scalar_one()


async def get_by_user_id(session: AsyncSession, user_id: uuid.UUID) -> StudentProfile | None:
    result = await session.execute(select(StudentProfile).where(StudentProfile.user_id == user_id))
    return result.scalar_one_or_none()


async def get_phone(session: AsyncSession, user_id: uuid.UUID) -> str | None:
    """The student's phone number (kept on the users row)."""
    result = await session.execute(select(User.phone).where(User.id == user_id))
    return result.scalar_one_or_none()


# TODO(Mogith): add the queries this module needs, one small async function each, e.g.
#   async def get_by_id(session: AsyncSession, id: uuid.UUID) -> StudentProfile | None:
#       return await session.get(StudentProfile, id)


async def most_common_exam_year(session: AsyncSession, from_year: int) -> int | None:
    """The exam year most students chose (this year or later) - the admin dashboard batch."""
    result = await session.execute(
        select(StudentProfile.exam_year)
        .where(StudentProfile.exam_year >= from_year)
        .group_by(StudentProfile.exam_year)
        .order_by(func.count().desc(), StudentProfile.exam_year)
        .limit(1)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------- account delete / export


async def get_settings_row(session: AsyncSession, user_id: uuid.UUID) -> UserSettings | None:
    return await session.get(UserSettings, user_id)


async def delete_user_rows(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Delete the student's profile, app settings and achievements. No commit."""
    await session.execute(delete(StudentProfile).where(StudentProfile.user_id == user_id))
    await session.execute(delete(UserSettings).where(UserSettings.user_id == user_id))
    await session.execute(delete(UserAchievement).where(UserAchievement.user_id == user_id))


# ---------------------------------------------------------------- settings / privacy


def add_settings_row(session: AsyncSession, row: UserSettings) -> None:
    session.add(row)


async def users_hiding_name(session: AsyncSession, user_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Which of these users turned "show my name in the community" off."""
    if not user_ids:
        return set()
    result = await session.scalars(
        select(UserSettings.user_id).where(
            UserSettings.user_id.in_(user_ids), UserSettings.show_name_in_community.is_(False)
        )
    )
    return set(result)


# ---------------------------------------------------------------- achievements


async def list_achievements(session: AsyncSession) -> list[Achievement]:
    """Active achievement definitions in display order."""
    result = await session.scalars(
        select(Achievement)
        .where(Achievement.is_active.is_(True))
        .order_by(Achievement.order_index, Achievement.id)
    )
    return list(result)


async def user_achievements(
    session: AsyncSession, user_id: uuid.UUID
) -> dict[str, UserAchievement]:
    """{achievement_id: unlock row} of one student."""
    result = await session.scalars(
        select(UserAchievement).where(UserAchievement.user_id == user_id)
    )
    return {row.achievement_id: row for row in result}


async def add_unlock(
    session: AsyncSession,
    user_id: uuid.UUID,
    achievement_id: str,
    unlocked_at: datetime,
    detail: str | None,
) -> bool:
    """Unlock once (a second, concurrent unlock does nothing). True if this call added it.
    No commit."""
    result = await session.execute(
        insert(UserAchievement)
        .values(
            user_id=user_id, achievement_id=achievement_id, unlocked_at=unlocked_at, detail=detail
        )
        .on_conflict_do_nothing(constraint="uq_user_achievements_user_achievement")
        .returning(UserAchievement.id)
    )
    return result.first() is not None


async def mark_seen(
    session: AsyncSession, user_id: uuid.UUID, achievement_id: str, seen_at: datetime
) -> bool:
    """Set seen_at on the student's own unlock (kept if already set). False if they never
    unlocked it. No commit."""
    found = await session.scalar(
        select(UserAchievement.id).where(
            UserAchievement.user_id == user_id, UserAchievement.achievement_id == achievement_id
        )
    )
    if found is None:
        return False
    await session.execute(
        update(UserAchievement)
        .where(UserAchievement.id == found, UserAchievement.seen_at.is_(None))
        .values(seen_at=seen_at)
    )
    return True
