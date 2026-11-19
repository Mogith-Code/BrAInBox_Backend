"""All SQL queries for the notifications module. Owner: Mogith.

Tables: notifications, device_tokens (push tokens)
Only this module's `service.py` may import this file.
"""

import uuid
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import DeviceToken, Notification


def add(session: AsyncSession, notification: Notification) -> None:
    """Saved with the caller's commit."""
    session.add(notification)


async def list_for_user(
    session: AsyncSession, user_id: uuid.UUID, *, limit: int, unread_only: bool
) -> list[Notification]:
    stmt = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    stmt = stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars())


async def count_unread(session: AsyncSession, user_id: uuid.UUID) -> int:
    result = await session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
    )
    return int(result or 0)


async def get_for_user(
    session: AsyncSession, user_id: uuid.UUID, notification_id: uuid.UUID
) -> Notification | None:
    row = await session.get(Notification, notification_id)
    return row if row is not None and row.user_id == user_id else None


async def mark_all_read(session: AsyncSession, user_id: uuid.UUID, now: datetime) -> int:
    result = await session.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=now)
        .returning(Notification.id)
    )
    return len(result.all())


# ---------------------------------------------------------------- account delete / export


async def count_devices(session: AsyncSession, user_id: uuid.UUID) -> int:
    """How many phones of the student get push notifications."""
    result = await session.execute(
        select(func.count()).select_from(DeviceToken).where(DeviceToken.user_id == user_id)
    )
    return result.scalar_one()


async def delete_user_rows(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Delete the student's notifications and push device tokens. No commit."""
    await session.execute(delete(Notification).where(Notification.user_id == user_id))
    await session.execute(delete(DeviceToken).where(DeviceToken.user_id == user_id))
