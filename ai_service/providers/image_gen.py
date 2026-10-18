"""Text-to-image adapter (Imagen via the google-genai SDK)."""


class GeminiImageGenerator:
    name = "imagen"

    def __init__(self, api_key: str, model: str):
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self.model = model

    async def generate_image(self, prompt: str) -> bytes:
        from google.genai import types

        response = await self._client.aio.models.generate_images(
            model=self.model,
            prompt=prompt,
            config=types.GenerateImagesConfig(number_of_images=1),
        )
        images = response.generated_images or []
        if not images or images[0].image is None or images[0].image.image_bytes is None:
            raise RuntimeError("Image model returned no image")
        # TODO(Mogith): add a safety / quality check before images are shown to students.
        return images[0].image.image_bytes
