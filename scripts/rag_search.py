"""RAG: try a query from the command line.

python scripts/rag_search.py --q "active transport"
python scripts/rag_search.py --q "active transport" --unit 2 --k 3
python scripts/rag_search.py --q "nephron" --source-type marking_scheme --show-context
"""

import argparse
import asyncio

import _bootstrap  # noqa: F401

from ai_service.rag.context_builder import build_context
from ai_service.rag.ingestion.pipeline import unit_id_for_number
from ai_service.rag.retrieval.retriever import retrieve
from shared.db.session import SessionLocal
from shared.enums import SourceType


async def run(args: argparse.Namespace) -> int:
    async with SessionLocal() as session:
        unit_id = await unit_id_for_number(session, args.unit) if args.unit else None
        if args.unit and unit_id is None:
            raise SystemExit(f"Unit {args.unit} not found. Run scripts/seed_syllabus.py first.")
        chunks = await retrieve(
            args.q,
            unit_id=unit_id,
            source_types=[args.source_type] if args.source_type else None,
            k=args.k,
            session=session,
        )

    if not chunks:
        print("No results. Did you run scripts/ingest_documents.py?")
        return 1
    for i, c in enumerate(chunks, 1):
        print(
            f"\n#{i} score={c.score:.3f} (vector={c.vector_score:.3f}, keyword={c.keyword_score:.3f})"
        )
        print(f"   {c.document_title} [{c.source_type}] page={c.page} | {c.heading_path}")
        print(f"   {c.text[:300]}{'...' if len(c.text) > 300 else ''}")
    if args.show_context:
        print("\n----- prompt context -----\n" + build_context(chunks).text)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Search the RAG index")
    parser.add_argument("--q", required=True, help="search text")
    parser.add_argument("--unit", type=int, help="filter by unit number 1-10")
    parser.add_argument("--source-type", type=SourceType, choices=list(SourceType))
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--show-context", action="store_true")
    raise SystemExit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
