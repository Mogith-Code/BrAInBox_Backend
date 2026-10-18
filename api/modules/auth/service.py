"""Business logic for the auth module. Owner: Mogith.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

from api.modules.auth.schemas import ModuleStatus

MODULE_NAME = "auth"


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


# TODO(Mogith): register(session, claims) -> create users row (role=student) if it does not exist
# TODO(Mogith): get_me / update_me / delete_me
