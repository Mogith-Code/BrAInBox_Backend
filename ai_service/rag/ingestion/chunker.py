"""Split cleaned pages into overlapping chunks and remember the heading path of each chunk.

* Size is measured in words, a simple stand-in for tokens (1 word ≈ 1.3 tokens).
* Consecutive chunks inside one section share `overlap` words, so a sentence cut at a
  boundary still appears whole in one of them.
* A new heading always starts a new chunk (no overlap across sections), so the
  `heading_path` of every chunk is exact.

Headings recognised:
    # Markdown headings (any level)         -> level = number of '#'
    2.3 Numbered headings (with a dot)      -> level = number of parts ("2.3" -> 2)
"""

import re

from ai_service.rag.ingestion.loaders import PageText
from ai_service.rag.schemas import Chunk

_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")
_NUMBERED_HEADING_RE = re.compile(r"^(\d+(?:\.\d+){1,3})\.?\s+([A-Z][^.!?]{0,100})$")


def parse_heading(line: str) -> tuple[int, str] | None:
    """Return (level, title) if `line` is a heading, otherwise None."""
    match = _MD_HEADING_RE.match(line)
    if match:
        return len(match.group(1)), match.group(2).strip()
    match = _NUMBERED_HEADING_RE.match(line)
    if match:
        return match.group(1).count(".") + 1, f"{match.group(1)} {match.group(2).strip()}"
    return None


def chunk_pages(pages: list[PageText], chunk_tokens: int = 500, overlap: int = 50) -> list[Chunk]:
    if chunk_tokens <= 0:
        raise ValueError("chunk_tokens must be positive")
    if not 0 <= overlap < chunk_tokens:
        raise ValueError("overlap must be >= 0 and smaller than chunk_tokens")

    chunks: list[Chunk] = []
    headings: list[tuple[int, str]] = []  # current heading stack, e.g. [(1, "Unit 2"), (2, ...)]
    buffer: list[tuple[str, int | None]] = []  # (word, page) waiting to become a chunk
    fresh = 0  # words in `buffer` that are not just overlap from the previous chunk

    def emit(keep_overlap: bool) -> None:
        nonlocal buffer, fresh
        if fresh > 0:
            chunks.append(
                Chunk(
                    chunk_index=len(chunks),
                    text=" ".join(word for word, _ in buffer),
                    heading_path=" > ".join(title for _, title in headings) or None,
                    page=buffer[0][1],
                    token_count=len(buffer),
                )
            )
        buffer = buffer[-overlap:] if (keep_overlap and overlap) else []
        fresh = 0

    for page in pages:
        for raw_line in page.text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            heading = parse_heading(line)
            if heading:
                emit(keep_overlap=False)  # close the previous section
                level, title = heading
                while headings and headings[-1][0] >= level:
                    headings.pop()
                headings.append((level, title))
                continue
            for word in line.split():
                buffer.append((word, page.page))
                fresh += 1
                if len(buffer) >= chunk_tokens:
                    emit(keep_overlap=True)

    emit(keep_overlap=False)
    return chunks


def chunk_text(text: str, chunk_tokens: int = 500, overlap: int = 50) -> list[Chunk]:
    """Convenience wrapper for a single block of text."""
    return chunk_pages([PageText(page=None, text=text)], chunk_tokens, overlap)
