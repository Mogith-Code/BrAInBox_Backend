"""Split an uploaded past paper (PDF) into questions. Owner: Udith.

Job type: EXTRACT_PAST_PAPER (dispatched by ai_service/routes/jobs.py)

    payload = {"past_paper_id": "...", "file_path": "past_papers/<id>.pdf",
               "paper_type": "paper_1_mcq" | "paper_2_structured"}
    result  = {"past_paper_id": "...", "pages": 12,
               "questions": [{"label": "Q3 (b)", "marks": 4, "text": "...",
                              "ocr_confidence": 0.93, "suggested_keywords": ["osmosis", ...]}]}

1. Read the text: the PDF's text layer, and Tesseract OCR for scanned pages
   (rag/ingestion/loaders.py, the same reader as uploads and RAG).
2. Split: a question starts with its number at the start of a line ("12." or "12)").
   Paper 2 questions are split again into parts "(a)", "(b)"... -> labels "Q3 (b)".
3. Per question: marks from "(4 marks)", a readability score (share of normal words),
   and up to 5 suggested keywords (the most frequent longer words). No LLM is used, so it is
   free and works without keys; the admin checks and edits every question afterwards.
"""

import asyncio
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from ai_service.errors import UserInputError
from ai_service.providers import get_storage
from ai_service.rag.ingestion.loaders import load_document

QUESTION_START = re.compile(r"(?m)^\s*(\d{1,2})\s*[.)]\s+")
PART_START = re.compile(r"(?m)^\s*\(([a-h])\)\s*")
MARKS = re.compile(r"\((\d{1,2})\s*marks?\)", re.IGNORECASE)
WORD = re.compile(r"[A-Za-z][A-Za-z\-']+")
TOKEN = re.compile(r"[A-Za-z][A-Za-z\-']*(/[A-Za-z]+)?")  # a word, incl. one-letter labels
MAX_QUESTIONS = 120
STOPWORDS = {
    "which", "following", "about", "their", "there", "these", "those", "would", "could",
    "should", "where", "while", "other", "because", "between", "describe", "explain", "state",
    "answer", "question", "marks", "correct", "statement", "statements", "given", "below",
    "above", "under", "during", "after", "before", "write", "shown", "shows", "diagram",
    "labelled", "named", "figure",
}  # fmt: skip


class NoQuestionsFoundError(UserInputError):
    code = "NO_QUESTIONS_FOUND"


def readability(text: str) -> float:
    """0-1: how much of the text looks like normal words (OCR noise lowers it)."""
    tokens = text.split()
    if not tokens:
        return 0.0
    good = 0
    for token in tokens:
        clean = token.strip(".,;:()[]?!\"'")
        if clean.isdigit() or TOKEN.fullmatch(clean):
            good += 1
    return round(good / len(tokens), 2)


def suggest_keywords(text: str, limit: int = 5) -> list[str]:
    words = [w.lower() for w in WORD.findall(text) if len(w) >= 5]
    counts = Counter(w for w in words if w not in STOPWORDS)
    return [w for w, _ in counts.most_common(limit)]


def _question(label: str, body: str) -> dict[str, Any]:
    body = body.strip()
    marks = MARKS.search(body)
    return {
        "label": label,
        "marks": int(marks.group(1)) if marks else None,
        "text": body,
        "ocr_confidence": readability(body),
        "suggested_keywords": suggest_keywords(body),
    }


def split_questions(text: str, paper_type: str) -> list[dict[str, Any]]:
    """Pure: the questions in a past paper's text, in order."""
    starts = list(QUESTION_START.finditer(text))
    questions: list[dict[str, Any]] = []
    for i, match in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        number, body = match.group(1), text[match.end() : end]
        parts = list(PART_START.finditer(body)) if paper_type == "paper_2_structured" else []
        if not parts:
            questions.append(_question(f"Q{number}", body))
            continue
        intro = body[: parts[0].start()].strip()
        for j, part in enumerate(parts):
            part_end = parts[j + 1].start() if j + 1 < len(parts) else len(body)
            part_text = body[part.end() : part_end]
            full = f"{intro}\n\n{part_text}".strip() if intro and j == 0 else part_text
            questions.append(_question(f"Q{number} ({part.group(1)})", full))
    return questions[:MAX_QUESTIONS]


async def read_pages(file_path: str) -> list[str]:
    """The text of every page (text layer + OCR for scanned pages). Tests replace this."""
    data = await get_storage().load(file_path)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "paper.pdf"
        path.write_bytes(data)
        try:
            pages = await asyncio.to_thread(load_document, path)
        except Exception as exc:
            raise UserInputError(
                "This file could not be opened. Is it a valid PDF?", code="UNREADABLE_FILE"
            ) from exc
    return [p.text or "" for p in pages]


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    file_path = str(payload.get("file_path") or "")
    paper_type = str(payload.get("paper_type") or "paper_1_mcq")
    if not file_path:
        raise UserInputError("file_path is required", code="INVALID_INPUT")
    pages = await read_pages(file_path)
    questions = split_questions("\n".join(pages), paper_type)
    if not questions:
        raise NoQuestionsFoundError(
            "No numbered questions were found. Is this a scanned paper without OCR?"
        )
    return {
        "past_paper_id": payload.get("past_paper_id"),
        "pages": len(pages),
        "questions": questions,
    }
