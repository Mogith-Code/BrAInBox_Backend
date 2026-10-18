"""Business logic for the profiles module. Owner: Mogith.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

from api.modules.profiles.schemas import ModuleStatus

MODULE_NAME = "profiles"


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


# TODO(Mogith): get_profile(user) / update_profile(user, data) (create on first PATCH)
