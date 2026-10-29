"""Prepare uploaded text before summarising (extract, clean, check). Owner: Samni.

    text = await load_upload_text("uploads/<user>/<upload>.pdf", "application/pdf")  # files only
    text = preprocess(text)                                                         # always

Every problem with the student's input raises a UserInputError subclass with its own code,
which the app shows to the student (see ai_service/errors.py).
"""

import asyncio
import logging
import tempfile
from pathlib import Path

from ai_service.config import get_settings
from ai_service.errors import UserInputError
from ai_service.providers import get_storage
from ai_service.rag.ingestion.cleaner import clean_pages, clean_text
from ai_service.rag.ingestion.loaders import load_document

logger = logging.getLogger(__name__)

# Upload types we can read, with the file extension the loaders expect.
FILE_SUFFIXES = {"application/pdf": ".pdf"}

MIN_LETTERS_FOR_LANGUAGE_CHECK = 50  # shorter texts are too short to judge
MIN_LATIN_SHARE = 0.5  # below this share of a-z letters the notes are probably not English


class EmptyTextError(UserInputError):
    """The notes were empty (or only whitespace / junk) after cleaning."""

    code = "EMPTY_NOTES"


class NoTextInFileError(EmptyTextError):
    """The file has no readable text (e.g. a scanned PDF and no OCR)."""

    code = "NO_TEXT_IN_FILE"


class TextTooLongError(UserInputError):
    code = "NOTES_TOO_LONG"


class NotEnglishError(UserInputError):
    code = "NOT_ENGLISH"


class UnsupportedFileError(UserInputError):
    code = "UNSUPPORTED_FILE_TYPE"


class UnreadableFileError(UserInputError):
    """The file could not be opened, e.g. a broken PDF."""

    code = "UNREADABLE_FILE"


def preprocess(text: str) -> str:
    """Return text ready for chunking. Raises a UserInputError if it cannot be summarised."""
    # Same cleaning as RAG ingestion: fix line endings, join hyphen breaks, drop page numbers.
    cleaned = clean_text(text)
    if not cleaned:
        raise EmptyTextError("The notes are empty, so there is nothing to summarise")

    max_chars = get_settings().MAX_INPUT_CHARS
    if len(cleaned) > max_chars:
        raise TextTooLongError(
            f"The notes are too long ({len(cleaned):,} characters, at most {max_chars:,}). "
            "Split them into smaller parts."
        )
    if not looks_english(cleaned):
        raise NotEnglishError("Only English notes can be summarised for now")
    return cleaned


def looks_english(text: str) -> bool:
    """True when most letters are a-z. Sinhala and Tamil letters are not, so those notes fail.

    A simple check on purpose (no extra library): Greek letters or a few symbols in Biology
    notes do not matter, because only the share of letters counts.
    """
    letters = [c for c in text if c.isalpha()]
    if len(letters) < MIN_LETTERS_FOR_LANGUAGE_CHECK:
        return True
    latin = sum(1 for c in letters if c.isascii())
    return latin / len(letters) >= MIN_LATIN_SHARE


async def load_upload_text(file_path: str, mime_type: str) -> str:
    """Download an uploaded file from storage and return its text (PDF only for now)."""
    suffix = FILE_SUFFIXES.get(mime_type)
    if suffix is None:
        raise UnsupportedFileError(f"Files of type '{mime_type}' cannot be summarised")

    data = await get_storage().load(file_path)

    # The loaders read from a path, so write the bytes to a temporary file first.
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / f"upload{suffix}"
        path.write_bytes(data)
        try:
            # Blocking work (pypdf, maybe OCR for scanned pages): run it in a worker thread.
            pages = await asyncio.to_thread(load_document, path)
        except Exception as exc:
            logger.warning("Could not read %s: %s", file_path, exc)
            raise UnreadableFileError("This file could not be opened. Is it a valid PDF?") from exc

    text = "\n\n".join(page.text for page in clean_pages(pages) if page.text)
    if not text.strip():
        raise NoTextInFileError(
            "We could not find any text in this file. It may be a scanned image: "
            "paste the text of your notes instead."
        )
    return text
