"""Read the photos of a handwritten answer.

Job type: OCR_ANSWER (dispatched by ai_service/routes/jobs.py)

Payload: {"image_paths": ["answers/<user>/<id>/page-1.jpg", ...]}
Result:  {"ocr_text": "...", "pages": [{"page": 1, "text": "...", "characters": 412}]}

The student sees the text and can correct it before it is evaluated.
"""

from typing import Any

from ai_service.errors import UserInputError
from ai_service.providers import get_ocr, get_storage

MAX_PAGES = 6


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    paths = [str(p) for p in (payload.get("image_paths") or [])][:MAX_PAGES]
    if not paths:
        raise UserInputError("Add at least one photo of your answer.", code="NO_PAGES")
    storage, ocr = get_storage(), get_ocr()
    pages = []
    for number, path in enumerate(paths, start=1):
        try:
            image = await storage.load(path)
        except Exception as exc:
            raise UserInputError(
                f"Page {number} could not be opened. Please upload it again.", code="PAGE_NOT_FOUND"
            ) from exc
        text = (await ocr.extract_text(image)).strip()
        pages.append({"page": number, "text": text, "characters": len(text)})
    full_text = "\n\n".join(p["text"] for p in pages if p["text"])
    if not full_text:
        raise UserInputError(
            "We couldn't read any writing in the photos. Try again with more light and the page "
            "flat, or type your answer.",
            code="OCR_EMPTY",
        )
    return {"ocr_text": full_text, "pages": pages}
