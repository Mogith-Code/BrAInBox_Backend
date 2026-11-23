"""The official resource books, shown to students as the real book pages. Owner: Samni.

The NIE books are scanned, so their pages are images. We never rewrite them: the app shows each
page exactly as printed. The text read during the RAG import is only used to find the page
where a topic starts.

Nothing here touches the database (see learn/service.py and learn/repository.py).
"""

import hashlib
import io
import logging
import re
import tempfile
import threading
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pypdfium2

from api.core import storage

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PAGE_SCALE = 2.0  # about 144 dpi: sharp on a phone, and still a small file
JPEG_QUALITY = 80
MATCH_FROM = 0.75  # share of the topic's words a passage must contain to count as a match
_STOP_WORDS = {"and", "the", "for", "with", "its", "their", "from"}

# The PDF library is not thread-safe, so only one thread may use it at a time.
_pdf_lock = threading.Lock()


@dataclass(frozen=True)
class Passage:
    """One imported piece of a book and the page it starts on."""

    document_id: uuid.UUID
    page: int
    text: str


@dataclass(frozen=True)
class StartPage:
    document_id: uuid.UUID
    page: int
    exact: bool  # True = the topic was found; False = open at the start of the unit


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", text.lower()) if w not in _STOP_WORDS}


def find_start_page(topic_title: str, passages: list[Passage]) -> StartPage | None:
    """Pure: the first passage with the topic's title, else the one sharing the most words.

    `passages` must be in reading order. Returns the first page of the unit when nothing matches
    well, because a wrong "exact" page would be worse than starting at the beginning.
    """
    if not passages:
        return None
    title = " ".join(topic_title.lower().split())
    for passage in passages:
        if title in " ".join(passage.text.lower().split()):
            return StartPage(passage.document_id, passage.page, True)

    wanted = _words(topic_title)
    best, best_score = passages[0], 0.0
    for passage in passages:
        score = len(wanted & _words(passage.text)) / max(len(wanted), 1)
        if score > best_score:  # ">" keeps the earliest page on a tie
            best, best_score = passage, score
    if best_score >= MATCH_FROM:
        return StartPage(best.document_id, best.page, True)
    first = passages[0]
    return StartPage(first.document_id, 1, False)


def book_title(title: str) -> str:
    """Pure: "Unit01 Introduction To Biology" -> "Unit 1: Introduction To Biology"."""
    match = re.match(r"unit\s*0*(\d+)\s+(.+)", title.strip(), re.IGNORECASE)
    return f"Unit {match.group(1)}: {match.group(2)}" if match else title


def local_book(stored_path: str) -> Path | None:
    """The PDF on this computer, only if it is inside the project's data folder."""
    data_folder = (PROJECT_ROOT / "data").resolve()
    path = (PROJECT_ROOT / stored_path).resolve()
    if path.suffix.lower() != ".pdf" or not path.is_relative_to(data_folder):
        return None
    return path if path.is_file() else None


def book_file(stored_path: str) -> Path | None:
    """The book as a local file, downloading it once from the bucket when needed.

    Blocking: call it with run_in_threadpool. None = the book can't be read on this server.
    """
    path = local_book(stored_path)
    if path is not None or storage.uses_local_files():
        return path
    if not stored_path.startswith("rag_sources/") or not stored_path.lower().endswith(".pdf"):
        return None
    name = hashlib.sha256(stored_path.encode()).hexdigest()
    cached = Path(tempfile.gettempdir()) / "brainbox_books" / f"{name}.pdf"
    if not cached.is_file():
        try:
            storage.download_to_file(stored_path, cached)
        except Exception:
            logger.exception("Could not download the official book %s", stored_path)
            return None
    return cached


@lru_cache(maxsize=64)
def _count_pages(path: str, modified: float) -> int:
    with _pdf_lock:
        pdf = pypdfium2.PdfDocument(path)
        try:
            return len(pdf)
        finally:
            pdf.close()


def page_count(path: Path) -> int:
    return _count_pages(str(path), path.stat().st_mtime)


@lru_cache(maxsize=128)
def _render(path: str, modified: float, page: int) -> bytes:
    with _pdf_lock:
        pdf = pypdfium2.PdfDocument(path)
        try:
            image = pdf[page - 1].render(scale=PAGE_SCALE).to_pil().convert("RGB")
        finally:
            pdf.close()
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return output.getvalue()


def render_page(path: Path, page: int) -> bytes:
    """One book page (first page = 1) as a JPEG. Recent pages are kept in memory."""
    return _render(str(path), path.stat().st_mtime, page)
