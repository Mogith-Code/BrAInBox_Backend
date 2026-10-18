"""Business logic for the recommendations module. Owner: Udith.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

from api.modules.recommendations.schemas import ModuleStatus

MODULE_NAME = "recommendations"


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


# TODO(Udith): list_recommendations (weak concepts from performance.service)
# TODO(Udith): search YouTube via youtube_client.py, rank via RANK_RESOURCES job
# TODO(Udith): study plan CRUD
