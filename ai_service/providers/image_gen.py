"""Text-to-image adapters. Pick one with IMAGE_PROVIDER (see providers/__init__.py).

  * GeminiImageGenerator     IMAGE_PROVIDER=gemini      (google-genai SDK)
  * CloudflareImageGenerator IMAGE_PROVIDER=cloudflare  (Workers AI REST API, FLUX.1 schnell)

Both return the raw image bytes the provider sent (PNG or JPEG). The visuals pipeline turns
them into a PNG and reads the size with Pillow, so adapters stay small.
"""

import base64

import httpx

from ai_service.daily_limits import use_quota


class GeminiImageGenerator:
    """Paid only: Google lists no free tier for its image models."""

    name = "gemini-image"
    quota_provider = "gemini"  # whose "day" the IMAGE_DAILY_LIMIT follows

    def __init__(self, api_key: str, model: str, daily_limit: int = 0):
        from google import genai  # imported here so the app starts without the SDK

        self._client = genai.Client(api_key=api_key)
        self.model = model
        self.daily_limit = daily_limit

    async def generate_image(self, prompt: str) -> bytes:
        await use_quota("gemini", "image", self.model, self.daily_limit, images=1)
        # Older Imagen models have their own endpoint (paid only).
        if self.model.startswith("imagen"):
            return await self._imagen(prompt)
        return await self._gemini(prompt)

    async def _gemini(self, prompt: str) -> bytes:
        """Gemini image models (e.g. gemini-2.5-flash-image) answer generate_content with
        the picture as an inline-data part."""
        from google.genai import types

        response = await self._client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
        )
        for candidate in response.candidates or []:
            content = candidate.content
            for part in (content.parts if content else None) or []:
                if part.inline_data and part.inline_data.data:
                    return part.inline_data.data
        raise RuntimeError("Image model returned no image")

    async def _imagen(self, prompt: str) -> bytes:
        from google.genai import types

        response = await self._client.aio.models.generate_images(
            model=self.model,
            prompt=prompt,
            config=types.GenerateImagesConfig(number_of_images=1),
        )
        images = response.generated_images or []
        if not images or images[0].image is None or images[0].image.image_bytes is None:
            raise RuntimeError("Image model returned no image")
        return images[0].image.image_bytes


class CloudflareImageGenerator:
    """Cloudflare Workers AI. The free plan has 10,000 "neurons" per day for all models.

    POST https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}
    body {"prompt": "...", "steps": 4} -> {"result": {"image": "<base64 JPEG>"}, "success": true}
    """

    name = "cloudflare-image"
    quota_provider = "cloudflare"
    STEPS = 4  # FLUX.1 schnell: 4 is the default, 8 is the maximum (more steps cost more)

    def __init__(
        self,
        account_id: str,
        api_token: str,
        model: str,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,  # tests pass a mock transport
        daily_limit: int = 0,  # pictures per day (00:00 UTC); 0 = no cap
    ):
        self.model = model
        self.daily_limit = daily_limit
        self._url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
        self._headers = {"Authorization": f"Bearer {api_token}"}
        self._timeout = timeout
        self._transport = transport

    async def generate_image(self, prompt: str) -> bytes:
        await use_quota("cloudflare", "image", self.model, self.daily_limit, images=1)
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            response = await client.post(
                self._url, headers=self._headers, json={"prompt": prompt, "steps": self.STEPS}
            )
            response.raise_for_status()
            data = response.json()
        # The REST API wraps the model output in "result"; accept the bare output too.
        output = data.get("result", data) if isinstance(data, dict) else {}
        image = output.get("image") if isinstance(output, dict) else None
        if not image:
            raise RuntimeError("Cloudflare returned no image")
        return base64.b64decode(image)
