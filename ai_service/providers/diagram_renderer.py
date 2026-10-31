"""Mermaid text -> PNG with Kroki (https://kroki.io), a free, open-source diagram server.

    POST {KROKI_URL}/mermaid/png   body = the Mermaid text (text/plain)   -> PNG bytes

Self-host it with Docker when kroki.io is slow or you do not want to send diagrams outside
(docs: https://docs.kroki.io/kroki/setup/install/). Kroki is not an AI model, but it is an
outside service, so it lives here in providers/ like the others.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class KrokiRenderer:
    name = "kroki"

    def __init__(
        self,
        base_url: str,
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,  # tests pass a mock transport
    ):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport

    async def render_png(self, mermaid_code: str) -> bytes | None:
        """PNG bytes, or None when Kroki is down / refuses the diagram.

        Never raises: the visual is still saved with its Mermaid code, and the app can
        render that itself.
        """
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{self._base_url}/mermaid/png",
                    content=mermaid_code.encode("utf-8"),
                    headers={"Content-Type": "text/plain"},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Kroki could not render the diagram: %s", exc)
            return None
        if not response.content.startswith(PNG_SIGNATURE):
            logger.warning("Kroki answered with something that is not a PNG")
            return None
        return response.content


class FakeDiagramRenderer:
    """Tests: never calls the network. Returns a tiny PNG (or None to act like Kroki is down)."""

    name = "fake-diagram"

    def __init__(self, png: bytes | None = None):
        from ai_service.providers.fakes import _TINY_PNG

        self.png = _TINY_PNG if png is None else png
        self.down = False
        self.calls: list[str] = []

    async def render_png(self, mermaid_code: str) -> bytes | None:
        self.calls.append(mermaid_code)
        return None if self.down else self.png
