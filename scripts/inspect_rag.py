"""RAG: health report of the ingested chunks. Ported from Udith's inspect_db.py (ChromaDB -> Postgres).

    python scripts/inspect_rag.py

Shows chunks per unit, leftover watermark text, and chunk-size statistics,
so you can check an ingestion run (e.g. after adding the NIE resource books).
"""

import asyncio

import _bootstrap  # noqa: F401
from sqlalchemy import func, select

from shared.db.models import DocumentChunk, SourceDocument, Unit
from shared.db.session import SessionLocal

JUNK_PHRASES = ("rights reserved", "national institute", "resource book")
SHORT_CHUNK_WORDS = 80


async def run() -> None:
    async with SessionLocal() as session:
        total = (
            await session.execute(select(func.count()).select_from(DocumentChunk))
        ).scalar_one()
        print("Total chunks:", total)
        if not total:
            print("Nothing ingested yet. Run scripts/ingest_documents.py.")
            return

        print("\nDocuments:")
        docs = await session.execute(
            select(SourceDocument.title, SourceDocument.status, SourceDocument.chunk_count)
        )
        for title, status, count in docs.all():
            print(f"  {title}  [{status}]  {count} chunks")

        print("\nChunks per unit:")
        per_unit = await session.execute(
            select(Unit.number, Unit.title, func.count(DocumentChunk.id))
            .select_from(DocumentChunk)
            .outerjoin(Unit, Unit.id == DocumentChunk.unit_id)
            .group_by(Unit.number, Unit.title)
            .order_by(Unit.number.nulls_last())
        )
        for number, title, count in per_unit.all():
            label = f"Unit {number}: {title}" if number else "No unit"
            print(f"  {label}  ->  {count} chunks")

        texts = (await session.execute(select(DocumentChunk.text))).scalars().all()

    print("\nChecks:")
    for phrase in JUNK_PHRASES:
        print(f"  chunks containing '{phrase}':", sum(phrase in t.lower() for t in texts))
    lengths = [len(t.split()) for t in texts]
    print(
        f"  words per chunk: min {min(lengths)}, max {max(lengths)}, "
        f"avg {sum(lengths) // len(lengths)}"
    )
    print(
        f"  very short chunks (< {SHORT_CHUNK_WORDS} words):",
        sum(n < SHORT_CHUNK_WORDS for n in lengths),
    )


if __name__ == "__main__":
    asyncio.run(run())
