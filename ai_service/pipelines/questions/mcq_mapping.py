"""Map wrong MCQ options to misconceptions. Owner: Udith.

Job type: MAP_MISCONCEPTIONS (dispatched by ai_service/routes/jobs.py)
"""

from typing import Any

PROMPT_NAME = "questions/map_misconceptions"
PROMPT_VERSION = 1


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Map wrong MCQ options to misconceptions."""
    # TODO(Udith):
    #   1. load the question + known misconceptions from the payload
    #   2. get_llm().generate_json(prompt, MisconceptionMappingSet)
    return {"status": "todo", "pipeline": "questions.mcq_mapping"}
