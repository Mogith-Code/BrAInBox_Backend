"""Turn retrieved chunks into a prompt context block with numbered source citations.

Output text looks like:

    [1] Approved notes - Cell membrane (p. 3) | Unit 2 > Cell membrane
    Active transport moves ions against the concentration gradient using ATP...

    [2] ...

Prompts tell the model to cite sources as [1], [2]. The `citations` list is saved with
the generated content (e.g. notes.citations) so admins can check where facts came from.
"""

import uuid

from pydantic import BaseModel

from ai_service.rag.schemas import RetrievedChunk


class Citation(BaseModel):
    ref: int  # the [n] number used in the context text
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    page: int | None = None
    heading_path: str | None = None


class BuiltContext(BaseModel):
    text: str
    citations: list[Citation]


def build_context(chunks: list[RetrievedChunk], max_chars: int = 8000) -> BuiltContext:
    """Add chunks in score order until `max_chars` is reached."""
    blocks: list[str] = []
    citations: list[Citation] = []
    used = 0
    for chunk in chunks:
        ref = len(citations) + 1
        header = f"[{ref}] {chunk.document_title}"
        if chunk.page:
            header += f" (p. {chunk.page})"
        if chunk.heading_path:
            header += f" | {chunk.heading_path}"
        block = f"{header}\n{chunk.text}"
        if blocks and used + len(block) > max_chars:
            break
        blocks.append(block)
        used += len(block)
        citations.append(
            Citation(
                ref=ref,
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                document_title=chunk.document_title,
                page=chunk.page,
                heading_path=chunk.heading_path,
            )
        )
    return BuiltContext(text="\n\n".join(blocks), citations=citations)
