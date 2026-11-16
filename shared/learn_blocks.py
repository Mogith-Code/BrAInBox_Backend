"""Learn tab note blocks: the exact JSON the Flutter app renders. Used by the api and ai_service.

A note's `blocks` is a list of:

    {"type": "heading",     "text": "1. Mendel's law of segregation"}
    {"type": "paragraph",   "text": "...", "highlights": ["alleles", "gamete formation"]}
    {"type": "definition",  "title": "Definition", "text": "Genotype - ..."}
    {"type": "tip",         "title": "Past-paper tip", "text": "2021 Paper II ..."}
    {"type": "bullet_list", "items": ["...", "..."]}
    {"type": "table",       "caption": "RrYy x RrYy", "headers": [...], "rows": [[...]]}
    {"type": "image",       "url": "...", "caption": "..."}

`parse_blocks()` accepts AI output (a JSON string, a list or {"blocks": [...]}) and REPAIRS what
it can: unknown keys are dropped, a block with a missing/unknown type or no text is skipped,
table rows are padded/cut to the header width, highlights that are not in the text are removed.
If no valid block is left it raises BlocksError.
"""

import json
import math
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

MAX_TEXT = 4000
MAX_BLOCKS = 200
WORDS_PER_MINUTE = 200  # reading speed used for read_minutes


class BlocksError(ValueError):
    """The input has no usable blocks (bad JSON, wrong shape, or every block invalid)."""


class _Block(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


def _text(max_length: int = MAX_TEXT) -> Any:
    return Field(min_length=1, max_length=max_length)


class HeadingBlock(_Block):
    type: Literal["heading"]
    text: str = _text(300)


class ParagraphBlock(_Block):
    type: Literal["paragraph"]
    text: str = _text()
    highlights: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("highlights", mode="before")
    @classmethod
    def _strings_only(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [v.strip() for v in value if isinstance(v, str) and v.strip()]


class DefinitionBlock(_Block):
    type: Literal["definition"]
    title: str = Field(default="Definition", min_length=1, max_length=200)
    text: str = _text()


class TipBlock(_Block):
    type: Literal["tip"]
    title: str = Field(default="Tip", min_length=1, max_length=200)
    text: str = _text()


class BulletListBlock(_Block):
    type: Literal["bullet_list"]
    items: list[str] = Field(min_length=1, max_length=50)

    @field_validator("items", mode="before")
    @classmethod
    def _clean_items(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(v).strip()[:MAX_TEXT] for v in value if str(v).strip()]


class TableBlock(_Block):
    type: Literal["table"]
    caption: str | None = Field(default=None, max_length=300)
    headers: list[str] = Field(min_length=1, max_length=12)
    rows: list[list[str]] = Field(min_length=1, max_length=100)

    @field_validator("headers", mode="before")
    @classmethod
    def _header_strings(cls, value: Any) -> list[str]:
        return [str(v) for v in value] if isinstance(value, list) else []

    @field_validator("rows", mode="before")
    @classmethod
    def _row_strings(cls, value: Any) -> list[list[str]]:
        if not isinstance(value, list):
            return []
        return [[str(c) for c in row] for row in value if isinstance(row, list) and row]


class ImageBlock(_Block):
    type: Literal["image"]
    url: str = Field(min_length=1, max_length=1000, pattern=r"^(https?://|/)")
    caption: str | None = Field(default=None, max_length=300)


Block = Annotated[
    HeadingBlock
    | ParagraphBlock
    | DefinitionBlock
    | TipBlock
    | BulletListBlock
    | TableBlock
    | ImageBlock,
    Field(discriminator="type"),
]
BLOCK_TYPES = ("heading", "paragraph", "definition", "tip", "bullet_list", "table", "image")

_block_adapter: TypeAdapter[Any] = TypeAdapter(Block)


def _loads(raw: str) -> Any:
    """JSON from an LLM answer: strips ```json fences and text around the JSON."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Some models add a sentence before/after: take the outermost [...] or {...}.
        for open_char, close_char in (("[", "]"), ("{", "}")):
            start, end = text.find(open_char), text.rfind(close_char)
            if start != -1 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    continue
    raise BlocksError("The answer is not valid JSON")


def _repair(block: dict[str, Any]) -> dict[str, Any]:
    """Small fixes before validation."""
    block = dict(block)
    kind = str(block.get("type", "")).strip().lower().replace("-", "_").replace(" ", "_")
    kind = {"bullets": "bullet_list", "list": "bullet_list", "bulletlist": "bullet_list"}.get(
        kind, kind
    )
    block["type"] = kind
    if kind == "table" and isinstance(block.get("headers"), list) and block["headers"]:
        width = len(block["headers"])
        rows = block.get("rows")
        if not isinstance(rows, list):
            rows = []
        block["rows"] = [
            (list(r) + [""] * width)[:width] for r in rows if isinstance(r, list) and r
        ]
    if kind == "paragraph" and isinstance(block.get("text"), str):
        text_lower = block["text"].lower()
        highlights = block.get("highlights")
        if isinstance(highlights, list):
            block["highlights"] = [
                h for h in highlights if isinstance(h, str) and h.strip().lower() in text_lower
            ]
    return block


def parse_blocks(raw: str | list[Any] | dict[str, Any]) -> list[dict[str, Any]]:
    """Validated (and repaired) blocks as plain dicts. Raises BlocksError if none are valid."""
    data = _loads(raw) if isinstance(raw, str) else raw
    if isinstance(data, dict):
        data = data.get("blocks")
    if not isinstance(data, list):
        raise BlocksError("Expected a JSON list of blocks")

    valid: list[dict[str, Any]] = []
    for item in data[:MAX_BLOCKS]:
        if not isinstance(item, dict):
            continue
        try:
            block = _block_adapter.validate_python(_repair(item))
        except ValidationError:
            continue
        valid.append(block.model_dump(exclude_none=True))
    if not valid:
        raise BlocksError("No valid blocks")
    return valid


def bullet_count(blocks: list[dict[str, Any]]) -> int:
    return sum(len(b["items"]) for b in blocks if b["type"] == "bullet_list")


def word_count(blocks: list[dict[str, Any]]) -> int:
    words = 0
    for b in blocks:
        parts: list[str] = [b.get("text", ""), b.get("title", ""), b.get("caption") or ""]
        parts += b.get("items", [])
        parts += b.get("headers", [])
        parts += [c for row in b.get("rows", []) for c in row]
        words += sum(len(p.split()) for p in parts)
    return words


def read_minutes(blocks: list[dict[str, Any]]) -> int:
    """Reading time in whole minutes (at least 1)."""
    return max(1, math.ceil(word_count(blocks) / WORDS_PER_MINUTE))


def to_markdown(blocks: list[dict[str, Any]]) -> str:
    """Markdown copy of the blocks (stored in notes.body_md for the admin portal and RAG)."""
    out: list[str] = []
    for b in blocks:
        kind = b["type"]
        if kind == "heading":
            out.append(f"## {b['text']}")
        elif kind == "paragraph":
            out.append(b["text"])
        elif kind in ("definition", "tip"):
            out.append(f"> **{b['title']}:** {b['text']}")
        elif kind == "bullet_list":
            out.append("\n".join(f"- {item}" for item in b["items"]))
        elif kind == "table":
            lines = [f"**{b['caption']}**"] if b.get("caption") else []
            lines.append("| " + " | ".join(b["headers"]) + " |")
            lines.append("|" + " --- |" * len(b["headers"]))
            lines += ["| " + " | ".join(row) + " |" for row in b["rows"]]
            out.append("\n".join(lines))
        elif kind == "image":
            out.append(f"![{b.get('caption') or ''}]({b['url']})")
    return "\n\n".join(out)
