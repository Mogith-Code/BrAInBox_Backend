"""Load source documents into plain text, page by page.

Supported: PDF (.pdf), Word (.docx), text (.txt) and Markdown (.md).
Sources: NIE syllabus, teacher guides, approved notes, marking schemes.
"""

from dataclasses import dataclass
from pathlib import Path

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


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
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    # TODO(Samni): scanned PDFs have no text layer -> send pages to OCR (providers/ocr_vision.py).
    return [
        PageText(page=i, text=page.extract_text() or "") for i, page in enumerate(reader.pages, 1)
    ]


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
