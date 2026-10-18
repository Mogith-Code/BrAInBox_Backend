"""Business logic for the visuals module. Owner: Mogith.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

from api.modules.visuals.schemas import ModuleStatus

MODULE_NAME = "visuals"


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


# TODO(Mogith): list_topic_visuals / request_visual (creates job) / report_visual
