"""Business logic for the questions module. Owner: Udith.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

from api.modules.questions.schemas import ModuleStatus

MODULE_NAME = "questions"


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


# TODO(Udith): get_question / list_topic_questions (approved only, hide is_correct)
# TODO(Udith): explain_mcq -> ai_client.sync('explain-mcq', ...)
