"""Learn tab upload summary: PDF / DOCX / TXT / image -> summary + 5-10 key points. Owner: Samni.

Job type: LEARN_UPLOAD_SUMMARY (dispatched by ai_service/routes/jobs.py)

    1. load the file the api stored (UPLOAD_DIR, or Storage uploads/learn/ with a bucket)
    2. extract text: PDF (pypdf, OCR for scanned pages when Tesseract is installed), DOCX
       (python-docx), TXT, images (Tesseract OCR; not installed -> OCR_NOT_AVAILABLE)
    3. long text -> split into parts, summarise each part (llm_client "summary_chunk"),
       then combine them in one final call
    4. final call answers JSON {"summary", "key_points"}; invalid -> ONE retry -> INVALID_AI_OUTPUT

payload = {
    "storage_path": "<user_id>/<upload_id>.pdf", "mime_type": "application/pdf",
    "summary_length": "short" | "medium" | "detailed",
    "topic_title": "Mendelian inheritance", "unit_title": "Genetics",   # optional
}
"""

import asyncio
import io
import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from ai_service.config import get_settings
from ai_service.errors import AIOutputError, UserInputError
from ai_service.pipelines.summarization.chunker import split_for_summary
from ai_service.pipelines.summarization.preprocess import (
    EmptyTextError,
    NoTextInFileError,
    TextTooLongError,
    UnreadableFileError,
    UnsupportedFileError,
)
from ai_service.prompts import prompt_id, render_prompt
from ai_service.providers import get_llm_client, get_storage
from ai_service.rag.ingestion.cleaner import clean_text
from ai_service.rag.ingestion.loaders import load_document, ocr_available

logger = logging.getLogger(__name__)

PROMPT = ("summarization/learn_upload_summary", 1)
CHUNK_PROMPT = ("summarization/summarize_chunk", 1)
STORAGE_PREFIX = "uploads/learn/"  # with a bucket (api/modules/learn/service.py uses the same)

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DOCUMENT_SUFFIXES = {"application/pdf": ".pdf", DOCX_MIME: ".docx", "text/plain": ".txt"}
IMAGE_MIME_TYPES = {"image/png", "image/jpeg"}

TARGET_WORDS = {"short": 120, "medium": 250, "detailed": 500}
MAX_PART_WORDS = 1500
MAX_PARTS = 24  # ~36,000 words; longer files are cut (a summary of a whole book is not useful)
MAX_PARALLEL_PARTS = 3
MAX_CHARS = 400_000
MAX_EXTRACTED_CHARS = 100_000  # kept on uploads.extracted_text
TEMPERATURE = 0.3


class OCRNotAvailableError(UserInputError):
    code = "OCR_NOT_AVAILABLE"


class UploadSummary(BaseModel):
    summary: str = Field(min_length=20)
    key_points: list[str] = Field(min_length=5)

    @field_validator("key_points", mode="before")
    @classmethod
    def _clean(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        points = [str(v).strip().lstrip("-•* ").strip() for v in value if str(v).strip()]
        return points[:10]  # more than 10 -> keep the first 10


# --------------------------------------------------------------------------- loading


async def load_file(storage_path: str) -> bytes:
    settings = get_settings()
    if settings.STORAGE_BUCKET:
        return await get_storage().load(STORAGE_PREFIX + storage_path)
    root = Path(settings.UPLOAD_DIR).resolve()
    file = (root / storage_path).resolve()
    if not file.is_relative_to(root):
        raise UnreadableFileError("Invalid upload path")
    try:
        return await asyncio.to_thread(file.read_bytes)
    except FileNotFoundError as exc:
        raise UnreadableFileError("The uploaded file was not found. Upload it again.") from exc


def _ocr_image(data: bytes) -> str:
    import pytesseract
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        return str(pytesseract.image_to_string(image, lang="eng"))


async def extract_text(data: bytes, mime_type: str) -> str:
    """The text of a file. Raises a UserInputError subclass the student can understand."""
    if mime_type in IMAGE_MIME_TYPES:
        if not ocr_available():
            raise OCRNotAvailableError(
                "OCR not available: text cannot be read from images on this server. "
                "Upload a PDF, DOCX or TXT file instead."
            )
        try:
            text = await asyncio.to_thread(_ocr_image, data)
        except Exception as exc:
            raise UnreadableFileError("This image could not be opened.") from exc
    else:
        suffix = DOCUMENT_SUFFIXES.get(mime_type)
        if suffix is None:
            raise UnsupportedFileError(f"Files of type '{mime_type}' cannot be summarised")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / f"upload{suffix}"
            path.write_bytes(data)
            try:
                pages = await asyncio.to_thread(load_document, path)
            except Exception as exc:
                logger.warning("Could not read upload (%s): %s", mime_type, exc)
                raise UnreadableFileError("This file could not be opened. Is it valid?") from exc
        text = "\n\n".join(p.text for p in pages if p.text)

    text = clean_text(text)
    if not text:
        if mime_type == "text/plain":
            raise EmptyTextError("The file is empty, so there is nothing to summarise")
        raise NoTextInFileError("We could not find any text in this file.")
    if len(text) > MAX_CHARS:
        raise TextTooLongError(
            f"The file has too much text ({len(text):,} characters, at most {MAX_CHARS:,})."
        )
    return text


# --------------------------------------------------------------------------- summarising


async def summarize_parts(parts: list[str], topic_title: str) -> str:
    client = get_llm_client()
    limit = asyncio.Semaphore(MAX_PARALLEL_PARTS)

    async def one(number: int, part: str) -> str:
        prompt = render_prompt(
            *CHUNK_PROMPT, chunk_text=part, chunk_number=number, total_chunks=len(parts)
        )
        async with limit:
            text = await client.complete(
                prompt,
                task="summary_chunk",
                meta={"topic_title": topic_title},
                temperature=TEMPERATURE,
                prompt_name=prompt_id(*CHUNK_PROMPT),
            )
        return f"Part {number}:\n{text.strip()}"

    return "\n\n".join(await asyncio.gather(*(one(n, p) for n, p in enumerate(parts, 1))))


def _parse_summary(raw: str) -> UploadSummary:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[4:] if text.lower().startswith("json") else text
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("not JSON")
    return UploadSummary.model_validate(json.loads(text[start : end + 1]))


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    storage_path = payload.get("storage_path") or ""
    mime_type = payload.get("mime_type") or ""
    length = payload.get("summary_length") or "medium"
    if not storage_path:
        raise UserInputError("storage_path is required", code="MISSING_FILE")
    if length not in TARGET_WORDS:
        raise UserInputError(f"Unknown summary_length '{length}'", code="INVALID_SUMMARY_LENGTH")
    topic_title = payload.get("topic_title") or ""

    text = await extract_text(await load_file(storage_path), mime_type)

    parts = split_for_summary(text, max_words=MAX_PART_WORDS)[:MAX_PARTS]
    from_parts = len(parts) > 1
    source_text = await summarize_parts(parts, topic_title) if from_parts else parts[0]

    prompt = render_prompt(
        *PROMPT,
        source_text=source_text,
        target_words=TARGET_WORDS[length],
        topic_title=topic_title,
        unit_title=payload.get("unit_title") or "",
        from_parts=from_parts,
    )
    client = get_llm_client()
    problem = ""
    for attempt in range(2):  # first try + ONE retry
        hint = (
            ""
            if attempt == 0
            else (
                f"\n\nYour previous answer could not be used ({problem}). "
                'Answer with ONLY {"summary": "...", "key_points": [5 to 10 strings]}.'
            )
        )
        raw = await client.complete(
            prompt + hint,
            task="upload_summary",
            meta={"topic_title": topic_title, "summary_length": length},
            temperature=TEMPERATURE,
            prompt_name=prompt_id(*PROMPT),
        )
        try:
            result = _parse_summary(raw)
            break
        except (ValueError, ValidationError) as exc:
            problem = "invalid JSON or fewer than 5 key points"
            logger.warning("Upload summary invalid on try %s: %s", attempt + 1, type(exc).__name__)
    else:
        raise AIOutputError("The AI returned an invalid summary twice. Please try again later.")

    return {
        "summary": result.summary.strip(),
        "key_points": result.key_points,
        "extracted_text": text[:MAX_EXTRACTED_CHARS],
        "parts": len(parts),
        "model": getattr(client, "name", None),
        "prompt_version": prompt_id(*PROMPT),
    }
