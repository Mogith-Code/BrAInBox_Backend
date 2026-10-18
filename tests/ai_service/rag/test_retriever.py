"""Ingest a small sample with fake embeddings, then retrieve it with a filter."""

import uuid
from pathlib import Path

import pytest

from ai_service.providers.fakes import FakeEmbedder
from ai_service.rag.context_builder import build_context
from ai_service.rag.indexing.embedder import embed_chunks
from ai_service.rag.indexing.vector_store import DocumentRef, InMemoryVectorStore
from ai_service.rag.ingestion.chunker import chunk_text
from ai_service.rag.ingestion.metadata import DocumentMetadata, attach_metadata
from ai_service.rag.retrieval.hybrid import merge_results
from ai_service.rag.retrieval.retriever import Retriever, retrieve
from ai_service.rag.schemas import RetrievalQuery, RetrievedChunk
from shared.enums import SourceType

UNIT_2 = uuid.uuid4()  # Chemical & Cellular Basis of Life
UNIT_6 = uuid.uuid4()  # Genetics

CELLS = """# Cell membrane and transport
Active transport moves ions against the concentration gradient using ATP and carrier proteins.

# Osmosis
Osmosis is the diffusion of water across a selectively permeable membrane.
"""
GENETICS = """# Mendelian inheritance
Mendel crossed pea plants and found dominant and recessive alleles.
"""


async def _store_with_two_documents() -> tuple[InMemoryVectorStore, FakeEmbedder]:
    store, embedder = InMemoryVectorStore(), FakeEmbedder()
    for text, unit_id, title in [(CELLS, UNIT_2, "Cells notes"), (GENETICS, UNIT_6, "Genetics")]:
        chunks = attach_metadata(chunk_text(text, 100, 10), DocumentMetadata(unit_id=unit_id))
        doc = DocumentRef(id=uuid.uuid4(), title=title, source_type=SourceType.APPROVED_NOTE)
        await store.add_chunks(doc, chunks, await embed_chunks(chunks, embedder))
    return store, embedder


async def test_retrieve_finds_sample_chunk():
    store, embedder = await _store_with_two_documents()
    results = await Retriever(store, embedder).retrieve(
        RetrievalQuery(query="active transport", k=3)
    )
    assert "Active transport" in results[0].text
    assert results[0].heading_path == "Cell membrane and transport"
    assert results[0].keyword_score > 0


async def test_retrieve_respects_unit_filter():
    store, embedder = await _store_with_two_documents()
    retriever = Retriever(store, embedder)
    genetics = await retriever.retrieve(RetrievalQuery(query="active transport", unit_id=UNIT_6))
    assert genetics and all(c.unit_id == UNIT_6 for c in genetics)
    teacher_guides = await retriever.retrieve(
        RetrievalQuery(query="osmosis", source_types=[SourceType.TEACHER_GUIDE])
    )
    assert teacher_guides == []


def _hit(score_v: float = 0.0, score_k: float = 0.0, chunk_id: uuid.UUID | None = None):
    return RetrievedChunk(
        chunk_id=chunk_id or uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_title="d",
        source_type=SourceType.SYLLABUS,
        text="t",
        vector_score=score_v,
        keyword_score=score_k,
    )


def test_hybrid_merge_combines_both_scores():
    shared_id = uuid.uuid4()
    vector = [_hit(score_v=0.9, chunk_id=shared_id), _hit(score_v=0.8)]
    keyword = [_hit(score_k=0.5, chunk_id=shared_id), _hit(score_k=0.1)]
    merged = merge_results(vector, keyword, vector_weight=0.6)
    assert merged[0].chunk_id == shared_id
    assert merged[0].score == pytest.approx(0.6 * 0.9 + 0.4 * 1.0)
    assert len(merged) == 3


def test_context_builder_numbers_citations():
    chunks = [_hit(score_v=0.9), _hit(score_v=0.5)]
    chunks[0].page, chunks[0].heading_path = 3, "Unit 2 > Osmosis"
    context = build_context(chunks)
    assert context.text.startswith("[1] d (p. 3) | Unit 2 > Osmosis\nt")
    assert [c.ref for c in context.citations] == [1, 2]
    assert context.citations[0].chunk_id == chunks[0].chunk_id


@pytest.mark.db
async def test_full_pipeline_on_postgres(db_session, tmp_path: Path):
    """load -> chunk -> fake embed -> pgvector + tsvector -> hybrid search -> delete."""
    from ai_service.rag.ingestion.pipeline import ingest_file
    from shared.db.models import SourceDocument

    marker = f"zebrafishmarker{uuid.uuid4().hex[:8]}"
    path = tmp_path / "sample_test_note.md"
    path.write_text(f"# Test topic\nThe {marker} protein is used in active transport tests.\n")

    result = await ingest_file(db_session, path, source_type=SourceType.APPROVED_NOTE)
    try:
        assert result.status == "ingested" and result.chunk_count == 1
        again = await ingest_file(db_session, path, source_type=SourceType.APPROVED_NOTE)
        assert again.status == "skipped"  # unchanged file -> idempotent

        hits = await retrieve(marker, source_types=[SourceType.APPROVED_NOTE], session=db_session)
        assert hits and marker in hits[0].text
        assert hits[0].keyword_score > 0  # found by Postgres full-text search too
    finally:
        doc = await db_session.get(SourceDocument, result.document_id)
        if doc:
            await db_session.delete(doc)
            await db_session.commit()
