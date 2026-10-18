"""Map-reduce summary of an upload. Owner: Samni.

Job type: SUMMARIZE_UPLOAD (dispatched by ai_service/routes/jobs.py)
"""

from typing import Any

PROMPT_NAME = "summarization/summarize_chunk"
PROMPT_VERSION = 1


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Map-reduce summary of an upload."""
    # TODO(Samni):
    #   1. text = preprocess(...); parts = split_for_summary(text)
    #   2. summarise each part with render_prompt(PROMPT_NAME, ...) + get_llm().generate
    #   3. merge the part summaries into one Markdown summary
    #   4. return {'body_md': ..., 'prompt_version': prompt_id(PROMPT_NAME, PROMPT_VERSION)}
    return {"status": "todo", "pipeline": "summarization.summarize"}
