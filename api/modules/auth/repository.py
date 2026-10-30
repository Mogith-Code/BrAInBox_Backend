"""All SQL queries for the auth module. Owner: Mogith.

Tables: users, email_codes, password_reset_tokens
Only this module's `service.py` may import this file.
"""

import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import EmailCode, PasswordResetToken, User


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
