"""Business logic for the questions module. Owner: Udith.

Rules:
  * SQL lives in `repository.py`, not here.
  * To use another module, call ITS service (e.g. `from api.modules.syllabus import service`),
    never its repository.
  * AI work goes through `api.core.ai_client` / `api.core.jobs`, never directly to a provider.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api.modules.questions import repository
from api.modules.questions.schemas import ModuleStatus

MODULE_NAME = "questions"


async def get_status() -> ModuleStatus:
    """Placeholder used by the status route."""
    return ModuleStatus(module=MODULE_NAME, status="todo")


async def get_example_questions(
    session: AsyncSession, topic_id: uuid.UUID, limit: int = 3
) -> list[dict[str, Any]]:
    """Approved MCQs shown to the AI as style examples when generating a paper."""
    rows = await repository.random_approved_mcqs(session, topic_id, limit)
    examples = []
    for question, options in rows:
        correct = next((o.text for o in options if o.is_correct), None)
        if correct is not None:
            examples.append(
                {
                    "question": question.stem,
                    "options": [o.text for o in options],
                    "correct_answer": correct,
                }
            )
    return examples


# TODO(Udith): get_question / list_topic_questions (approved only, hide is_correct)
# TODO(Udith): explain_mcq -> ai_client.sync('explain-mcq', ...)
