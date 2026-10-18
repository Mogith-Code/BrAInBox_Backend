"""Business logic for the quizzes module. Owner: Udith.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

from api.modules.quizzes.schemas import ModuleStatus

MODULE_NAME = "quizzes"


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


# TODO(Udith): start_quiz / submit_responses / get_results
# TODO(Udith): after grading call performance.service to record mistakes + update mastery
