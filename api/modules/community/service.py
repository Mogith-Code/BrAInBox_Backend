"""Business logic for the community module. Owner: Mogith.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

from api.modules.community.schemas import ModuleStatus

MODULE_NAME = "community"


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


# TODO(Mogith): groups / posts / replies / votes / reports; auto-tag via ai_client.sync('tag-post')
