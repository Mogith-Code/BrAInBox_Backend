"""Interfaces (Protocols) every AI provider adapter must follow.

Pipelines depend on these interfaces, never on a concrete SDK, so we can swap
Gemini for another provider (or for the fakes in tests) without touching pipeline code.
"""

from typing import Protocol, TypeVar

from pydantic import BaseModel

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class LLMProvider(Protocol):
    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float | None = None,
        prompt_name: str | None = None,
    ) -> str:
        """Return plain text."""
        ...

    async def generate_json(
        self,
        prompt: str,
        schema: type[SchemaT],
        *,
        system: str | None = None,
        temperature: float | None = None,
        prompt_name: str | None = None,
    ) -> SchemaT:
        """Return a validated Pydantic object of type `schema` (structured output)."""
        ...


class EmbeddingProvider(Protocol):
    dim: int

    async def embed(self, texts: list[str], *, task: str = "document") -> list[list[float]]:
        """One vector per text. task = "document" (for storing) or "query" (for searching)."""
        ...


class OCRProvider(Protocol):
    async def extract_text(self, image_bytes: bytes) -> str:
        """Read (handwritten or printed) text from an image."""
        ...


class ImageProvider(Protocol):
    async def generate_image(self, prompt: str) -> bytes:
        """Return PNG bytes."""
        ...


class StorageProvider(Protocol):
    async def save(self, path: str, data: bytes, content_type: str) -> str:
        """Store bytes and return the storage path."""
        ...

    async def load(self, path: str) -> bytes: ...
