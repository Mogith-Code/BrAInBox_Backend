"""RAG: ingest documents into source_documents + document_chunks.

    python scripts/ingest_documents.py                          # everything in data/rag_sources
    python scripts/ingest_documents.py --force                  # re-ingest unchanged files too
    python scripts/ingest_documents.py --path data/rag_sources/approved_notes/x.md --unit 2

Uses the fake embedder when USE_FAKE_AI=true or GEMINI_API_KEY is empty.
Run it in the ai_service container:  docker compose exec ai_service python scripts/ingest_documents.py
"""

import argparse
import asyncio
from pathlib import Path

import _bootstrap  # noqa: F401

from ai_service.providers import provider_names
from ai_service.rag.ingestion.pipeline import (
    SOURCE_DIRS,
    IngestResult,
    ingest_directory,
    ingest_file,
    unit_id_for_number,
)
from shared.db.session import SessionLocal
from shared.enums import SourceType

DEFAULT_ROOT = Path("data/rag_sources")


def guess_source_type(path: Path) -> SourceType:
    """Use the parent folder name (approved_notes -> approved_note)."""
    for part in reversed(path.parts):
        if part in SOURCE_DIRS:
            return SOURCE_DIRS[part]
    raise SystemExit(f"Cannot tell the source type of {path}; pass --source-type")


async def run(args: argparse.Namespace) -> int:
    print(f"Providers: {provider_names()}")
    async with SessionLocal() as session:
        if args.path.is_dir():
            results = await ingest_directory(session, args.path, force=args.force)
        else:
            unit_id = await unit_id_for_number(session, args.unit) if args.unit else None
            if args.unit and unit_id is None:
                raise SystemExit(f"Unit {args.unit} not found. Run scripts/seed_syllabus.py first.")
            source_type = args.source_type or guess_source_type(args.path)
            results = [
                await ingest_file(
                    session,
                    args.path,
                    source_type=source_type,
                    title=args.title,
                    unit_id=unit_id,
                    year=args.year,
                    force=args.force,
                )
            ]
    return report(results)


def report(results: list[IngestResult]) -> int:
    if not results:
        print("No supported files found (.pdf, .docx, .txt, .md).")
    for r in results:
        line = f"  [{r.status:>8}] {r.path}  chunks={r.chunk_count}"
        print(line + (f"  error={r.error}" if r.error else ""))
    failed = sum(r.status == "failed" for r in results)
    print(f"Done: {len(results)} file(s), {failed} failed.")
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest RAG source documents")
    parser.add_argument("--path", type=Path, default=DEFAULT_ROOT, help="a folder or one file")
    parser.add_argument("--force", action="store_true", help="re-ingest even if unchanged")
    parser.add_argument("--source-type", type=SourceType, choices=list(SourceType))
    parser.add_argument("--unit", type=int, help="unit number 1-10 (single file only)")
    parser.add_argument("--title", help="document title (single file only)")
    parser.add_argument("--year", type=int, help="e.g. marking scheme year (single file only)")
    raise SystemExit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
