"""All SQL queries for the auth module. Owner: Mogith.

Tables: users, email_codes, password_reset_tokens
Read-only for the admin Students list: student_profiles, study_activity.
Only this module's `service.py` may import this file.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, and_, case, cast, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import EmailCode, PasswordResetToken, StudentProfile, StudyActivity, User
from shared.enums import UserRole


async def count_users(session: AsyncSession) -> int:
    """Example query showing the pattern."""
    result = await session.execute(select(func.count()).select_from(User))
    return result.scalar_one()


# ---------------------------------------------------------------- users
async def get_user_by_uid(session: AsyncSession, firebase_uid: str) -> User | None:
    result = await session.execute(select(User).where(User.firebase_uid == firebase_uid))
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    """Case-insensitive match (emails are saved lower-case, but old rows may not be)."""
    result = await session.execute(select(User).where(func.lower(User.email) == email.lower()))
    return result.scalars().first()


# ---------------------------------------------------------------- email codes
async def latest_code(session: AsyncSession, email: str, purpose: str) -> EmailCode | None:
    """The newest code row for this email + purpose (used or not)."""
    result = await session.execute(
        select(EmailCode)
        .where(EmailCode.email == email, EmailCode.purpose == purpose)
        .order_by(EmailCode.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def close_open_codes(session: AsyncSession, email: str, purpose: str, now: datetime) -> None:
    """A new code makes every older unused code for the same purpose invalid."""
    await session.execute(
        update(EmailCode)
        .where(
            EmailCode.email == email,
            EmailCode.purpose == purpose,
            EmailCode.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )


# ---------------------------------------------------------------- reset tokens
async def get_reset_token(session: AsyncSession, token_hash: str) -> PasswordResetToken | None:
    result = await session.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    return result.scalar_one_or_none()


async def close_reset_tokens(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> None:
    """Mark every unused reset token of the user as used."""
    await session.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user_id, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )


# ---------------------------------------------------------------- admin: Students list
@dataclass
class StudentRow:
    user: User
    school: str | None
    district: str | None
    exam_year: int | None
    last_active_at: datetime | None
    status: str  # active | suspended | inactive


def _students_query(inactive_before: date) -> tuple[Any, Any]:
    """(SELECT of users with their profile + last study activity, the status expression)."""
    activity = (
        select(
            StudyActivity.user_id,
            func.max(StudyActivity.activity_date).label("last_day"),
            func.max(StudyActivity.created_at).label("last_at"),
        )
        .group_by(StudyActivity.user_id)
        .subquery()
    )
    # No study activity yet: count from the day the account was made.
    last_day = func.coalesce(activity.c.last_day, cast(User.created_at, Date))
    status = case(
        (User.is_active.is_(False), "suspended"),
        (last_day < inactive_before, "inactive"),
        else_="active",
    )
    stmt = (
        select(
            User,
            StudentProfile.school,
            StudentProfile.district,
            StudentProfile.exam_year,
            activity.c.last_at,
            status.label("status"),
        )
        .outerjoin(StudentProfile, StudentProfile.user_id == User.id)
        .outerjoin(activity, activity.c.user_id == User.id)
    )
    return stmt, status


def _row(r: Any) -> StudentRow:
    return StudentRow(r[0], r.school, r.district, r.exam_year, r.last_at, r.status)


async def list_students(
    session: AsyncSession,
    *,
    inactive_before: date,
    search: str | None,
    exam_year: int | None,
    district: str | None,
    status: str | None,
    offset: int,
    limit: int,
) -> tuple[list[StudentRow], int, int]:
    """(one page of students, total matching, how many of the matching ones are active).

    `active_total` ignores the status filter, so the header count stays the same while the
    admin switches between Active / Suspended / Inactive.
    """
    stmt, status_expr = _students_query(inactive_before)
    filters = [User.role == UserRole.STUDENT]
    if search and search.strip():
        pattern = f"%{search.strip().lower()}%"
        filters.append(
            or_(
                func.lower(func.coalesce(User.display_name, "")).like(pattern),
                func.lower(func.coalesce(User.email, "")).like(pattern),
            )
        )
    if exam_year is not None:
        filters.append(StudentProfile.exam_year == exam_year)
    if district and district.strip():
        filters.append(func.lower(StudentProfile.district) == district.strip().lower())
    base = stmt.where(and_(*filters))
    filtered = base.where(status_expr == status) if status else base

    total = await session.execute(select(func.count()).select_from(filtered.subquery()))
    matching = base.subquery()
    active_total = await session.execute(
        select(func.count()).select_from(matching).where(matching.c.status == "active")
    )
    rows = await session.execute(
        filtered.order_by(func.lower(func.coalesce(User.display_name, User.email)), User.id)
        .offset(offset)
        .limit(limit)
    )
    return [_row(r) for r in rows.all()], int(total.scalar_one()), int(active_total.scalar_one())


async def get_student_row(
    session: AsyncSession, user_id: uuid.UUID, inactive_before: date
) -> StudentRow | None:
    """One user (any role) in the same shape as the list."""
    stmt, _ = _students_query(inactive_before)
    row = (await session.execute(stmt.where(User.id == user_id))).first()
    return _row(row) if row else None
