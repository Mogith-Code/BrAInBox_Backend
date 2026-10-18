"""Business logic for the evaluation module. Owner: Keshomigha.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

from api.modules.evaluation.schemas import ModuleStatus

MODULE_NAME = "evaluation"


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


# TODO(Keshomigha): create_evaluation (job) / create_ocr_evaluation (job) / get_evaluation
# TODO(Keshomigha): load the model answer via knowledge_base.service (never its repository)
