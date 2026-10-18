"""Deterministic fake providers.

Used in tests and whenever no API keys are configured (USE_FAKE_AI=true), so the
whole system runs offline and for free. Same input -> same output, always.
"""

import hashlib
import math
import re
import types
import typing
from typing import Any, TypeVar

from pydantic import BaseModel

SchemaT = TypeVar("SchemaT", bound=BaseModel)

_WORD_RE = re.compile(r"[a-z0-9]+")

# 1x1 transparent PNG
_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


class FakeLLM:
    """Echo-style LLM. `generate_json` returns `schema.fake_example()` or fills required fields."""

    name = "fake-llm"

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float | None = None,
        prompt_name: str | None = None,
    ) -> str:
        digest = hashlib.sha256(prompt.encode()).hexdigest()[:8]
        return f"[fake-llm {digest}] {prompt[:200]}"

    async def generate_json(
        self,
        prompt: str,
        schema: type[SchemaT],
        *,
        system: str | None = None,
        temperature: float | None = None,
        prompt_name: str | None = None,
    ) -> SchemaT:
        # A schema with validators (e.g. "answer must be one of the options") can provide
        # its own valid sample through a `fake_example()` classmethod.
        example = getattr(schema, "fake_example", None)
        data = example() if callable(example) else _fake_data(schema)
        return schema.model_validate(data)


def _fake_value(annotation: Any) -> Any:
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        return _fake_value(args[0]) if args else None
    if origin is typing.Literal:
        return typing.get_args(annotation)[0]
    if origin in (list, set, tuple):
        return []
    if origin is dict:
        return {}
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _fake_data(annotation)
    simple = {str: "fake", int: 0, float: 0.0, bool: False}
    if isinstance(annotation, type):
        for base, value in simple.items():
            if issubclass(annotation, base):
                # Enums: take the first member
                members = getattr(annotation, "__members__", None)
                return next(iter(members.values())) if members else value
    return None


def _fake_data(schema: type[BaseModel]) -> dict[str, Any]:
    """Build a dict with a value for every required field of `schema`."""
    return {
        name: _fake_value(field.annotation)
        for name, field in schema.model_fields.items()
        if field.is_required()
    }


class FakeEmbedder:
    """Hashing bag-of-words embedder.

    Every word is hashed to one of `dim` positions, then the vector is L2-normalised.
    Texts that share words get a high cosine similarity, which is enough to test retrieval.
    """

    name = "fake-embedder"

    def __init__(self, dim: int = 768):
        self.dim = dim

    def embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for word in _WORD_RE.findall(text.lower()):
            h = int.from_bytes(hashlib.sha256(word.encode()).digest()[:8], "big")
            vector[h % self.dim] += 1.0 if (h >> 32) & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            # Empty text: return a fixed unit vector so cosine distance is still defined.
            vector[0] = 1.0
            return vector
        return [v / norm for v in vector]

    async def embed(self, texts: list[str], *, task: str = "document") -> list[list[float]]:
        return [self.embed_one(t) for t in texts]


class FakeOCR:
    name = "fake-ocr"

    async def extract_text(self, image_bytes: bytes) -> str:
        digest = hashlib.sha256(image_bytes).hexdigest()[:8]
        return f"[fake-ocr {digest}] {len(image_bytes)} bytes of handwriting"


class FakeImageGenerator:
    name = "fake-image"

    async def generate_image(self, prompt: str) -> bytes:
        return _TINY_PNG


class FakeStorage:
    """Keeps files in memory."""

    name = "fake-storage"

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def save(self, path: str, data: bytes, content_type: str) -> str:
        self.files[path] = data
        return path

    async def load(self, path: str) -> bytes:
        return self.files[path]
