"""Business logic for the profiles module. Owner: Mogith.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from api.modules.profiles import repository
from api.modules.profiles.schemas import ModuleStatus

MODULE_NAME = "profiles"


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


async def get_onboarding_flags(session: AsyncSession, user_id: uuid.UUID) -> tuple[bool, bool]:
    """(profile_completed, diagnostic_skipped) for the auth module's UserOut."""
    profile = await repository.get_by_user_id(session, user_id)
    if profile is None:
        return False, False
    return profile.profile_completed_at is not None, profile.diagnostic_skipped_at is not None


# TODO(Mogith): get_profile(user) / update_profile(user, data) (create on first PATCH)
