"""Business logic for the quality module. Owner: Udith.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

from api.modules.quality.schemas import ModuleStatus

MODULE_NAME = "quality"


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


# TODO(Udith): report_question / list_review_queue / record_review
# TODO(Udith): update_question_stats(question_id, is_correct, time_spent)
