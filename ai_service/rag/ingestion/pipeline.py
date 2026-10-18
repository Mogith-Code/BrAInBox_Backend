"""Ingestion pipeline: load -> clean -> chunk -> attach metadata -> embed -> store.

Idempotent: a file whose SHA-256 has not changed since the last successful run is skipped
(use force=True to re-ingest anyway). Used by:
  * scripts/ingest_documents.py          (CLI, whole folder or one file)
  * the RAG_INGEST job (routes/jobs.py)  (admin upload / reindex)
"""

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.config import get_settings
from ai_service.providers.base import EmbeddingProvider
from ai_service.rag.indexing.embedder import embed_chunks
from ai_service.rag.indexing.vector_store import DocumentRef, PgVectorStore
from ai_service.rag.ingestion.chunker import chunk_pages
from ai_service.rag.ingestion.cleaner import clean_pages
from ai_service.rag.ingestion.loaders import SUPPORTED_EXTENSIONS, load_document
from ai_service.rag.ingestion.metadata import DocumentMetadata, TopicRef, attach_metadata
from shared.db.models import SourceDocument, Topic, Unit
from shared.db.session import SessionLocal
from shared.enums import DocumentStatus, SourceType

logger = logging.getLogger(__name__)

# data/rag_sources/<folder>/ -> source type
SOURCE_DIRS: dict[str, SourceType] = {
    "syllabus": SourceType.SYLLABUS,
    "teacher_guides": SourceType.TEACHER_GUIDE,
    "approved_notes": SourceType.APPROVED_NOTE,
    "marking_schemes": SourceType.MARKING_SCHEME,
}


# "unit2_chemical_basis.pdf", "Unit-10 Applied Biology.pdf" -> 2, 10 (Udith's file naming)
_UNIT_IN_FILENAME_RE = re.compile(r"^unit[\s_-]*0*(\d{1,2})(?!\d)", re.IGNORECASE)


def unit_number_from_filename(name: str) -> int | None:
    match = _UNIT_IN_FILENAME_RE.match(name)
    return int(match.group(1)) if match else None


@dataclass
class IngestResult:
    path: str
    status: str  # "ingested" | "skipped" | "failed"
    document_id: uuid.UUID | None = None
    chunk_count: int = 0
    error: str | None = None


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def storage_key(path: Path) -> str:
    """Path saved in source_documents.file_path (relative to the project when possible)."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


async def unit_id_for_number(session: AsyncSession, number: int) -> uuid.UUID | None:
    result = await session.execute(select(Unit.id).where(Unit.number == number))
    return result.scalar_one_or_none()


async def _load_topics(session: AsyncSession, unit_id: uuid.UUID | None) -> list[TopicRef]:
    stmt = select(Topic.id, Topic.unit_id, Topic.title)
    if unit_id:
        stmt = stmt.where(Topic.unit_id == unit_id)
    rows = (await session.execute(stmt)).all()
    return [TopicRef(id=r[0], unit_id=r[1], title=r[2]) for r in rows]


async def ingest_file(
    session: AsyncSession,
    path: Path,
    *,
    source_type: SourceType,
    title: str | None = None,
    unit_id: uuid.UUID | None = None,
    year: int | None = None,
    force: bool = False,
    embedder: EmbeddingProvider | None = None,
) -> IngestResult:
    settings = get_settings()
    key = storage_key(path)
    sha = file_sha256(path)
    if unit_id is None and (number := unit_number_from_filename(path.name)):
        unit_id = await unit_id_for_number(session, number)

    doc = (
        await session.execute(select(SourceDocument).where(SourceDocument.file_path == key))
    ).scalar_one_or_none()

    if doc and doc.sha256 == sha and doc.status == DocumentStatus.READY and not force:
        return IngestResult(key, "skipped", doc.id, doc.chunk_count)

    # 1. Create / update the document row and commit it, so a failure can be recorded on it.
    if doc is None:
        doc = SourceDocument(
            title=title or path.stem.replace("_", " ").replace("-", " ").title(),
            source_type=source_type,
            file_path=key,
        )
        session.add(doc)
    elif title:
        doc.title = title
    doc.source_type = source_type
    doc.unit_id = unit_id or doc.unit_id
    doc.year = year or doc.year
    doc.sha256 = sha
    doc.status = DocumentStatus.INGESTING
    doc.error_message = None
    await session.commit()
    doc_id = doc.id

    # 2. Process the file and replace the old chunks in one transaction.
    try:
        pages = clean_pages(load_document(path))
        chunks = chunk_pages(pages, settings.RAG_CHUNK_TOKENS, settings.RAG_CHUNK_OVERLAP)
        topics = await _load_topics(session, doc.unit_id)
        attach_metadata(chunks, DocumentMetadata(unit_id=doc.unit_id, topics=topics))
        embeddings = await embed_chunks(chunks, embedder)

        store = PgVectorStore(session)
        await store.delete_document_chunks(doc_id)
        await store.add_chunks(DocumentRef(doc_id, doc.title, doc.source_type), chunks, embeddings)
        doc.chunk_count = len(chunks)
        doc.status = DocumentStatus.READY
        await session.commit()
        logger.info("Ingested %s (%s chunks)", key, len(chunks))
        return IngestResult(key, "ingested", doc_id, len(chunks))
    except Exception as exc:
        logger.exception("Ingestion failed for %s", key)
        await session.rollback()
        failed = await session.get(SourceDocument, doc_id)
        if failed:
            failed.status = DocumentStatus.FAILED
            failed.error_message = str(exc)[:2000]
            await session.commit()
        return IngestResult(key, "failed", doc_id, 0, str(exc))


def discover_files(root: Path) -> list[tuple[Path, SourceType]]:
    """Every supported file under root/<syllabus|teacher_guides|...>/ (README.md skipped)."""
    found = []
    for folder, source_type in SOURCE_DIRS.items():
        directory = root / folder
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if (
                path.is_file()
                and path.suffix.lower() in SUPPORTED_EXTENSIONS
                and not path.name.startswith(".")
                and path.name.lower() != "readme.md"
            ):
                found.append((path, source_type))
    return found


async def ingest_directory(
    session: AsyncSession,
    root: Path,
    *,
    force: bool = False,
    embedder: EmbeddingProvider | None = None,
) -> list[IngestResult]:
    results = []
    for path, source_type in discover_files(root):
        results.append(
            await ingest_file(
                session, path, source_type=source_type, force=force, embedder=embedder
            )
        )
    return results


async def run_job(payload: dict[str, Any]) -> dict[str, Any]:
    """RAG_INGEST job: payload = {"document_id": "...", "force": false}."""
    document_id = uuid.UUID(str(payload["document_id"]))
    async with SessionLocal() as session:
        doc = await session.get(SourceDocument, document_id)
        if doc is None:
            raise ValueError(f"source document {document_id} not found")
        path = Path(doc.file_path)
        if not path.exists():
            # TODO(Samni): download the file from Firebase Storage (providers.get_storage())
            #   into a temp folder when the admin uploaded it through the api.
            raise FileNotFoundError(f"{doc.file_path} is not available locally")
        result = await ingest_file(
            session,
            path,
            source_type=doc.source_type,
            force=bool(payload.get("force", False)),
        )
    return {
        "document_id": str(document_id),
        "status": result.status,
        "chunk_count": result.chunk_count,
        "error": result.error,
    }
