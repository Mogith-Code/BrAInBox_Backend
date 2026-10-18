"""Prepare uploaded text before summarising (extract, clean, detect language). Owner: Samni."""


def preprocess(text: str) -> str:
    """Return text ready for chunking."""
    # TODO(Samni): reuse ai_service.rag.ingestion.cleaner.clean_text and add upload-specific rules.
    return text.strip()


# TODO(Samni):
#   - download the upload from storage (providers.get_storage())
#   - extract text (reuse rag.ingestion.loaders + cleaner)
#   - reject non-English / empty files with a clear error
