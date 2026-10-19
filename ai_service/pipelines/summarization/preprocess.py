"""Prepare uploaded text before summarising (extract, clean, detect language). Owner: Samni."""

from ai_service.rag.ingestion.cleaner import clean_text


class EmptyTextError(ValueError):
    """The notes were empty (or only whitespace / junk) after cleaning."""


def preprocess(text: str) -> str:
    """Return text ready for chunking. Raises EmptyTextError if nothing is left."""
    # Same cleaning as RAG ingestion: fix line endings, join hyphen breaks, drop page numbers.
    cleaned = clean_text(text)
    if not cleaned:
        raise EmptyTextError("The notes are empty, so there is nothing to summarise")
    return cleaned


# TODO(Samni):
#   - download the upload from storage (providers.get_storage())
#   - extract text (reuse rag.ingestion.loaders)
#   - reject non-English files with a clear error
