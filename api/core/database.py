"""FastAPI dependency that gives each request its own database session.

Usage in a router:
    async def my_route(session: SessionDep): ...
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.session import SessionLocal


async def get_session() -> AsyncIterator[AsyncSession]:
    """Open a session for one request and always close it afterwards.

    Services call `await session.commit()` themselves when they write.
    """
    async with SessionLocal() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
