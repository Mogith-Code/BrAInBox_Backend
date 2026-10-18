"""Read a handwritten answer photo. Owner: Keshomigha.

Job type: OCR_ANSWER (dispatched by ai_service/routes/jobs.py)
"""

from typing import Any


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    """Read a handwritten answer photo."""
    # TODO(Keshomigha):
    #   1. image = await get_storage().load(payload['image_path'])
    #   2. text = await get_ocr().extract_text(image)
    #   3. return {'ocr_text': text} (the api then creates the EVALUATE_ANSWER job)
    return {"status": "todo", "pipeline": "evaluation.ocr"}
