"""SQL for admin-only tables (currently just `audit_log`).

Admin routes that manage other data use the owning module's service instead.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models import AuditLog


async def count_audit_log(session: AsyncSession) -> int:
    """Example query showing the pattern (replace with real queries)."""
    result = await session.execute(select(func.count()).select_from(AuditLog))
    return result.scalar_one()


# TODO(Mogith): insert_audit_entry(session, ...) and list_audit_entries(session, offset, limit)
