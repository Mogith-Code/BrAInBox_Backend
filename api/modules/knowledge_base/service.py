"""Business logic for the knowledge_base module. Owner: Keshomigha.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

from api.modules.knowledge_base.schemas import ModuleStatus

MODULE_NAME = "knowledge_base"


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


# TODO(Keshomigha): get_marking_scheme(question_id) -> model answer + points + keywords
