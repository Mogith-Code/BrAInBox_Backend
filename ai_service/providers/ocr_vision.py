"""OCR adapter: Google Cloud Vision (document text detection, works for handwriting).

Credentials: GOOGLE_APPLICATION_CREDENTIALS (service account JSON, never committed).
"""

from ai_service.config import get_settings


class VisionOCR:
    name = "google-vision"

    def __init__(self) -> None:
        from google.cloud import vision

        self._vision = vision
        self._client = vision.ImageAnnotatorAsyncClient()

    async def extract_text(self, image_bytes: bytes) -> str:
        vision = self._vision
        hints = [h.strip() for h in get_settings().OCR_LANGUAGE_HINTS.split(",") if h.strip()]
        request = vision.AnnotateImageRequest(
            image=vision.Image(content=image_bytes),
            features=[vision.Feature(type_=vision.Feature.Type.DOCUMENT_TEXT_DETECTION)],
            image_context=vision.ImageContext(language_hints=hints),
        )
        # The async client has no document_text_detection() helper, so use the batch call.
        batch = await self._client.batch_annotate_images(requests=[request])
        response = batch.responses[0]
        if response.error.message:
            raise RuntimeError(f"Vision OCR error: {response.error.message}")
        # TODO(Keshomigha): also return per-word confidence for low-confidence warnings.
        return str(response.full_text_annotation.text or "")
