"""Load source documents into plain text, page by page.

Supported: PDF (.pdf), Word (.docx), text (.txt) and Markdown (.md).
Sources: NIE syllabus, teacher guides, approved notes, marking schemes.
"""

import logging
import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ai_service.config import get_settings

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}

# A PDF page with fewer words than this is probably a scanned image -> OCR it.
MIN_WORDS_FOR_TEXT_LAYER = 30
OCR_DPI = 200
WINDOWS_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")


@dataclass
class PageText:
    page: int | None  # 1-based page number (None when the format has no pages)
    text: str


def load_document(path: Path) -> list[PageText]:
    """Return the text of a document as a list of pages."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _load_pdf(path)
    if suffix == ".docx":
        return _load_docx(path)
    if suffix in {".txt", ".md"}:
        return [PageText(page=None, text=path.read_text(encoding="utf-8", errors="replace"))]
    raise ValueError(f"Unsupported file type: {path.name}")


def _load_pdf(path: Path) -> list[PageText]:
    """Text layer of every page; scanned pages are read with Tesseract OCR when it is installed.

    OCR fallback ported from Udith's ingest_pdfs.py (page rendering uses pypdfium2).
    """
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    texts = [page.extract_text() or "" for page in reader.pages]
    scanned = [i for i, t in enumerate(texts) if len(t.split()) < MIN_WORDS_FOR_TEXT_LAYER]
    if scanned:
        if ocr_available():
            logger.info("%s: OCR on %s scanned page(s)", path.name, len(scanned))
            for i, text in _ocr_pdf_pages(path, scanned).items():
                if len(text.split()) > len(texts[i].split()):
                    texts[i] = text
        else:
            logger.warning(
                "%s: pages %s have almost no text and Tesseract is not installed",
                path.name,
                [i + 1 for i in scanned],
            )
    return [PageText(page=i, text=t) for i, t in enumerate(texts, 1)]


@lru_cache
def ocr_available() -> bool:
    """True when pytesseract + pypdfium2 are installed and the tesseract program is found."""
    try:
        import pypdfium2  # noqa: F401
        import pytesseract
    except ImportError:
        return False
    configured = get_settings().TESSERACT_CMD
    command: str | None
    if configured:
        command = configured if Path(configured).exists() else None
    elif WINDOWS_TESSERACT.exists():
        command = str(WINDOWS_TESSERACT)
    else:
        command = shutil.which("tesseract")
    if not command:
        return False
    pytesseract.pytesseract.tesseract_cmd = command
    return True


def _ocr_pdf_pages(path: Path, indexes: list[int]) -> dict[int, str]:
    """OCR the given 0-based page indexes. Returns {index: text}."""
    import pypdfium2
    import pytesseract

    pdf = pypdfium2.PdfDocument(str(path))
    try:
        result = {}
        for i in indexes:
            image = pdf[i].render(scale=OCR_DPI / 72).to_pil()
            result[i] = str(pytesseract.image_to_string(image, lang="eng"))
        return result
    finally:
        pdf.close()


def _load_docx(path: Path) -> list[PageText]:
    import docx

    document = docx.Document(str(path))
    lines = []
    for paragraph in document.paragraphs:
        style = (paragraph.style.name or "").lower() if paragraph.style else ""
        # Turn Word headings into Markdown headings so the chunker can track them.
        if style.startswith("heading"):
            level = style.replace("heading", "").strip()
            hashes = "#" * int(level) if level.isdigit() else "#"
            lines.append(f"{hashes} {paragraph.text}")
        else:
            lines.append(paragraph.text)
    return [PageText(page=None, text="\n\n".join(lines))]
