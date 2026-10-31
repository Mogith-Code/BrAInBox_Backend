"""Plan one visual for a student's request, then build it. Owner: Mogith.

Job type: GENERATE_VISUAL (dispatched by ai_service/routes/jobs.py)

Steps:
  1. RAG: find syllabus / approved-note facts for the topic (retriever + context_builder).
  2. LLM (prompt decide_visual.v2): safety check + kind + title + Mermaid code or image prompt
     + numbered labels + alt text, as validated JSON (VisualDecision).
  3a. diagram / flowchart / table: validate the Mermaid code, render a PNG with Kroki and store
      it. Kroki down? The visual is still made with its Mermaid code only (the app renders it).
  3b. illustration: the image model draws the picture (no text in it) and we store it.
  4. Return everything; the api saves it on the `visuals` row (api/modules/visuals/service.py).
"""

import logging
import uuid
from typing import Any

from pydantic import ValidationError

from ai_service.errors import UserInputError
from ai_service.pipelines.visuals import illustration
from ai_service.pipelines.visuals.diagram_mermaid import validate_mermaid
from ai_service.prompts import prompt_id, render_prompt
from ai_service.providers import get_diagram_renderer, get_llm
from ai_service.rag.context_builder import BuiltContext, build_context
from ai_service.rag.retrieval.retriever import retrieve
from ai_service.schemas.llm_outputs import VisualDecision, VisualLabel
from shared.enums import SourceType

logger = logging.getLogger(__name__)

PROMPT_NAME = "visuals/decide_visual"
PROMPT_VERSION = 2
PROMPT_ID = prompt_id(PROMPT_NAME, PROMPT_VERSION)  # saved in visuals.prompt_version

SOURCE_TYPES = [SourceType.SYLLABUS, SourceType.TEACHER_GUIDE, SourceType.APPROVED_NOTE]
MAX_RETRIES = 2  # extra LLM attempts when the JSON or the Mermaid code is invalid
TEMPERATURE = 0.3
MAX_LABELS = 12
MERMAID_KINDS = ("diagram", "flowchart", "table")

# The student's "visual type" card -> what we suggest to the LLM
KIND_HINTS = {
    "process": "a flowchart of the steps",
    "comparison": "a table (or a flowchart) that compares the items side by side",
    "structure": "a labelled diagram, or an illustration if a picture really helps",
}
STYLES = ("flat_colour", "textbook_line", "cross_section")

NOT_BIOLOGY_MESSAGE = "I can only draw Biology visuals."


class NotBiologyError(UserInputError):
    """The request is not about Biology study (the safety check failed)."""

    code = "NOT_BIOLOGY"


async def gather_context(query: str, topic_id: uuid.UUID | None) -> BuiltContext:
    """Syllabus facts for the prompt. Same pattern as notes/generate_notes.py."""
    chunks = await retrieve(query, topic_id=topic_id, source_types=SOURCE_TYPES, k=4)
    return build_context(chunks, max_chars=3000)


async def decide(prompt: str) -> VisualDecision:
    """Ask the LLM for a decision. Retries when the JSON or the Mermaid code is invalid."""
    errors: list[str] = []
    for _ in range(MAX_RETRIES + 1):
        try:
            decision = await get_llm().generate_json(
                prompt, VisualDecision, temperature=TEMPERATURE, prompt_name=PROMPT_ID
            )
        except ValidationError as exc:
            errors.append(", ".join(".".join(map(str, e["loc"])) for e in exc.errors()))
            continue
        if not decision.is_biology or decision.kind not in MERMAID_KINDS:
            return decision
        try:
            decision.mermaid_code = validate_mermaid(decision.mermaid_code)
            return decision
        except ValueError as exc:
            errors.append(str(exc))
    raise RuntimeError(f"LLM output was invalid after retries ({'; '.join(errors)})")


def clean_labels(labels: list[VisualLabel], *, with_positions: bool) -> list[dict[str, Any]]:
    """Number the labels 1, 2, 3... and keep x / y only for illustrations (clamped to 0-1)."""

    def clamp(value: float | None) -> float | None:
        return None if value is None else min(1.0, max(0.0, value))

    cleaned = []
    for number, label in enumerate(labels[:MAX_LABELS], start=1):
        cleaned.append(
            {
                "number": number,
                "name": label.name.strip(),
                "description": label.description.strip(),
                "x": clamp(label.x) if with_positions else None,
                "y": clamp(label.y) if with_positions else None,
            }
        )
    return [label for label in cleaned if label["name"]]


def storage_path(payload: dict[str, Any], visual_id: str) -> str:
    """visuals/{concept_id or topic_id or "general"}/{visual_id}.png"""
    folder = payload.get("concept_id") or payload.get("topic_id") or "general"
    return f"visuals/{folder}/{visual_id}.png"


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    """GENERATE_VISUAL job.

    payload = {
        "visual_id": "...",          # required: the draft row the api created
        "prompt": "nephron structure",
        "visual_type": "structure",  # process | structure | comparison
        "style": "flat_colour",      # flat_colour | textbook_line | cross_section
        "topic_title": "Excretion",  # optional ("" when no topic was picked)
        "topic_id": "...",           # optional: narrows the RAG search + storage folder
        "concept_name": "...",       # optional
        "concept_id": "...",         # optional
    }
    """
    visual_id = str(payload.get("visual_id") or "")
    student_prompt = (payload.get("prompt") or "").strip()
    visual_type = payload.get("visual_type") or "structure"
    style = payload.get("style") or "flat_colour"
    if not visual_id or not student_prompt:
        raise UserInputError("visual_id and prompt are required", code="INVALID_INPUT")
    if visual_type not in KIND_HINTS or style not in STYLES:
        raise UserInputError("Unknown visual type or style", code="INVALID_INPUT")
    topic_title = payload.get("topic_title") or ""
    topic_id = uuid.UUID(payload["topic_id"]) if payload.get("topic_id") else None

    # 1. RAG grounding. A visual can still be made without it (e.g. nothing ingested yet).
    context_text = ""
    try:
        context = await gather_context(f"{topic_title} {student_prompt}".strip(), topic_id)
        context_text = context.text
    except Exception:
        logger.warning("RAG search failed for visual %s; continuing without it", visual_id)

    # 2. Decide (includes the safety check).
    prompt = render_prompt(
        PROMPT_NAME,
        PROMPT_VERSION,
        prompt=student_prompt,
        visual_type=visual_type,
        kind_hint=KIND_HINTS[visual_type],
        style=style,
        topic_title=topic_title,
        concept_name=payload.get("concept_name") or "",
        context=context_text,
    )
    decision = await decide(prompt)
    if not decision.is_biology:
        raise NotBiologyError(NOT_BIOLOGY_MESSAGE)

    # 3. Build the picture.
    path = storage_path(payload, visual_id)
    image_path: str | None = None
    width: int | None = None
    height: int | None = None
    mermaid_code: str | None = None
    if decision.kind == "illustration":
        description = (decision.image_prompt or decision.title).strip()
        stored = await illustration.create_illustration(description, style, path)
        image_path, width, height = stored.path, stored.width, stored.height
    else:
        mermaid_code = decision.mermaid_code
        png = await get_diagram_renderer().render_png(mermaid_code or "")
        if png is not None:
            stored = await illustration.save_png(path, png)
            image_path, width, height = stored.path, stored.width, stored.height

    llm = get_llm()
    return {
        "visual_id": visual_id,
        "kind": decision.kind,
        "title": decision.title.strip()[:200] or student_prompt[:200],
        "mermaid_code": mermaid_code,
        "image_path": image_path,
        "width": width,
        "height": height,
        "labels": clean_labels(decision.labels, with_positions=decision.kind == "illustration"),
        "alt_text": decision.alt_text.strip() or None,
        "style": style,
        "safety_passed": True,
        "prompt_version": PROMPT_ID,
        "model": getattr(llm, "model", None) or getattr(llm, "name", None),
    }
