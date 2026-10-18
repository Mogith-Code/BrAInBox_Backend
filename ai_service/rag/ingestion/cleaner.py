"""Clean extracted text: remove repeated headers/footers and page numbers, fix whitespace."""

import re
from collections import Counter

from ai_service.rag.ingestion.loaders import PageText

_PAGE_NUMBER_RE = re.compile(r"^\s*(page\s*)?\d+(\s*(of|/)\s*\d+)?\s*$", re.IGNORECASE)
_HYPHEN_BREAK_RE = re.compile(r"(\w)-\n(\w)")  # "photo-\nsynthesis" -> "photosynthesis"
_SPACES_RE = re.compile(r"[ \t]+")
_MANY_NEWLINES_RE = re.compile(r"\n{3,}")

# Watermark / running-header text of the NIE resource books, removed from every page
# (from Udith's ingest_pdfs.py).
_JUNK_PATTERNS = [
    re.compile(
        r"©?\s*\d{4}\s+National\s+Institute\s+of\s+Education\W*\s*All\s+Rights\s+Reserved\W*",
        re.IGNORECASE,
    ),
    re.compile(
        r"G\W*C\W*E\W*\(?\s*Advanced\s+Level\s*\)?\s*Biology\s+Resource\s+Book", re.IGNORECASE
    ),
]
_OCR_BULLET_RE = re.compile(r"(?m)^[ \t]*[¢•][ \t]+")  # bullet marks OCR leaves at line starts


def clean_pages(pages: list[PageText]) -> list[PageText]:
    """Clean every page. Lines repeated on most pages are treated as headers/footers."""
    repeated = _repeated_lines(pages)
    return [PageText(page=p.page, text=clean_text(p.text, drop_lines=repeated)) for p in pages]


def clean_text(text: str, drop_lines: set[str] | None = None) -> str:
    drop_lines = drop_lines or set()
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _HYPHEN_BREAK_RE.sub(r"\1\2", text)
    for pattern in _JUNK_PATTERNS:
        text = pattern.sub(" ", text)
    text = _OCR_BULLET_RE.sub("", text)
    kept = []
    for line in text.split("\n"):
        line = _SPACES_RE.sub(" ", line).strip()
        if _PAGE_NUMBER_RE.match(line) or line in drop_lines:
            continue
        kept.append(line)
    return _MANY_NEWLINES_RE.sub("\n\n", "\n".join(kept)).strip()


def _repeated_lines(pages: list[PageText], min_pages: int = 3) -> set[str]:
    """Short lines that appear on more than half of the pages (only for 3+ pages)."""
    if len(pages) < min_pages:
        return set()
    counts: Counter[str] = Counter()
    for page in pages:
        lines = {_SPACES_RE.sub(" ", ln).strip() for ln in page.text.splitlines()}
        counts.update(ln for ln in lines if ln and len(ln) < 80)
    return {line for line, n in counts.items() if n > len(pages) / 2}
