"""Attach syllabus position (unit / topic / concept) to chunks, so retrieval can filter.

Document-level metadata (unit, source type, year) comes from the `source_documents` row.
The topic is guessed from the chunk's heading path by matching topic titles.
"""

import uuid
from dataclasses import dataclass, field

from ai_service.rag.schemas import Chunk


@dataclass
class TopicRef:
    id: uuid.UUID
    unit_id: uuid.UUID
    title: str


@dataclass
class DocumentMetadata:
    unit_id: uuid.UUID | None = None
    topics: list[TopicRef] = field(default_factory=list)  # topics to match against headings


def match_topic(heading_path: str | None, topics: list[TopicRef]) -> TopicRef | None:
    """Return the topic whose title appears in the heading path (longest title wins)."""
    if not heading_path:
        return None
    path = heading_path.lower()
    matches = [t for t in topics if t.title.lower() in path]
    return max(matches, key=lambda t: len(t.title)) if matches else None


def attach_metadata(chunks: list[Chunk], meta: DocumentMetadata) -> list[Chunk]:
    for chunk in chunks:
        chunk.unit_id = meta.unit_id
        topic = match_topic(chunk.heading_path, meta.topics)
        if topic:
            chunk.topic_id = topic.id
            chunk.unit_id = chunk.unit_id or topic.unit_id
        # TODO(Samni): set concept_id (e.g. match concept names, or nearest concept embedding).
    return chunks
