"""Business logic for the quizzes module. Owner: Udith.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from api.modules.quizzes import repository
from api.modules.quizzes.schemas import ModuleStatus

MODULE_NAME = "quizzes"


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


async def has_completed_diagnostic(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """True once the student has submitted a diagnostic test."""
    return await repository.has_graded_diagnostic(session, user_id)


# TODO(Udith): start_quiz / submit_responses / get_results
# TODO(Udith): after grading call performance.service to record mistakes + update mastery
