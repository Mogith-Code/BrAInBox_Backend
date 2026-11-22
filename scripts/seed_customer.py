"""Seed a fresh database with everything the customer's app needs, in one command.

    python scripts/seed_customer.py --admin-email owner@school.lk
    python scripts/seed_customer.py --skip knowledge-base       # e.g. no Gemini key yet
    python scripts/seed_customer.py --only past-papers question-bank

Run it after `alembic upgrade head`, with DATABASE_URL (and the other production settings)
pointing at the customer's database. Install both extras first: pip install -e ".[api,ai]".

Safe to run any number of times: every step matches existing rows and only adds what is
missing (see each script's own notes). Steps, in order:

  syllabus        data/syllabus/al_biology_syllabus.json: units, topics, sub-topics
                  (scripts/seed_syllabus.py)
  base            community groups and app settings (scripts/seed_dev.py, without samples)
  learn           Learn tab subjects/topics + the official Mendelian inheritance note
                  (scripts/seed_learn.py; uploads its diagram to STORAGE_BUCKET)
  past-papers     every data/questions/<year>_<part>.json, e.g. 2023_part_1.json, imported as
                  an approved past paper (scripts/import_past_papers.py). The example file is
                  never imported.
  question-bank   data/questions/question_bank.json as approved MCQs
                  (scripts/import_question_bank.py). A question whose topic matches no
                  seeded topic is skipped with a WARNING at the end (the rest are imported).
  knowledge-base  the approved documents in data/rag_sources/* for the AI's answers (RAG,
                  scripts/ingest_documents.py). Needs a real GEMINI_API_KEY: fake embeddings
                  are refused outside dev/test. Files named sample_* are skipped.
  admin           --admin-email becomes an admin (scripts/make_admin.py). The person must
                  have signed in once (app or Firebase console) first.

The first failing step stops the run (later steps need the syllabus); fix it and run again.
"""

import argparse
import asyncio
import re
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

QUESTIONS_DIR = REPO_ROOT / "data" / "questions"
RAG_DIR = REPO_ROOT / "data" / "rag_sources"
# One past paper per file: 2023_part_1.json, 2019_part_2a.json, 2019_part_2b.json
PAST_PAPER_FILE_RE = re.compile(r"^\d{4}_part_(1|2a|2b)\.json$")

StepFn = Callable[[argparse.Namespace], Awaitable[None]]


# Problems that do not stop the run, repeated at the end so they are not missed.
WARNINGS: list[str] = []


class StepFailed(Exception):
    """A step could not finish; the message says what to fix."""


def past_paper_files(directory: Path) -> list[Path]:
    """The past paper files in `directory`, oldest year first (never the example file)."""
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if PAST_PAPER_FILE_RE.match(p.name))


# --------------------------------------------------------------------------- steps


async def step_syllabus(args: argparse.Namespace) -> None:
    import seed_syllabus

    await seed_syllabus.seed(seed_syllabus.DEFAULT_FILE)


async def step_base(args: argparse.Namespace) -> None:
    import seed_dev

    counts = await seed_dev.seed(with_samples=False)
    added = ", ".join(f"{n} {what}" for what, n in counts.added.items()) or "nothing new"
    print(f"Base data: {added}")


async def step_learn(args: argparse.Namespace) -> None:
    import seed_learn

    result = await seed_learn.seed()
    print(f"Learn tab: {result}")


async def step_past_papers(args: argparse.Namespace) -> None:
    import import_past_papers

    files = past_paper_files(args.questions_dir)
    if not files:
        print(f"No past paper files (<year>_<part>.json) in {args.questions_dir}; skipped.")
        return
    for path in files:
        if await import_past_papers.run(path, dry_run=False) != 0:
            raise StepFailed(f"{path.name} has problems (listed above); nothing was written")


async def step_question_bank(args: argparse.Namespace) -> None:
    import import_question_bank

    path = args.questions_dir / "question_bank.json"
    if not path.is_file():
        print(f"No {path}; skipped.")
        return
    if await import_question_bank.run(path) != 0:
        # The questions that match a topic are imported; the others are listed above.
        WARNINGS.append(
            "question-bank: some questions were not imported (their topic matches no seeded "
            "topic); fix the topic names in question_bank.json and run again"
        )


async def step_knowledge_base(args: argparse.Namespace) -> None:
    try:
        from ai_service.config import get_settings as get_ai_settings
        from ai_service.rag.ingestion.pipeline import discover_files, ingest_file
    except ImportError as exc:
        raise StepFailed(
            f"the AI packages are not installed ({exc.name}): pip install -e '.[api,ai]'"
        ) from exc
    from shared.db.session import SessionLocal

    settings = get_ai_settings()
    if settings.use_fakes and settings.ENVIRONMENT not in ("dev", "test"):
        raise StepFailed(
            "real embeddings are needed: set GEMINI_API_KEY and USE_FAKE_AI=false "
            "(or run with --skip knowledge-base and ingest later)"
        )
    files = [
        (path, source_type)
        for path, source_type in discover_files(args.rag_dir)
        if args.include_samples or not path.name.lower().startswith("sample_")
    ]
    if not files:
        print(f"No approved documents in {args.rag_dir}/*; skipped.")
        return
    failed = []
    async with SessionLocal() as session:
        for path, source_type in files:
            # Unchanged files (same content hash) are skipped, so re-running costs nothing.
            result = await ingest_file(session, path, source_type=source_type)
            print(f"  [{result.status:>8}] {path.name}  chunks={result.chunk_count}")
            if result.status == "failed":
                failed.append(f"{path.name}: {result.error}")
    if failed:
        raise StepFailed("could not ingest " + "; ".join(failed))


async def step_admin(args: argparse.Namespace) -> None:
    if not args.admin_email:
        print("No --admin-email given; no admin made (run scripts/make_admin.py later).")
        return
    import make_admin

    from shared.db.session import SessionLocal

    async with SessionLocal() as session:
        try:
            print(await make_admin.make_admin(session, args.admin_email))
        except LookupError as exc:
            raise StepFailed(str(exc)) from exc


STEPS: dict[str, StepFn] = {
    "syllabus": step_syllabus,
    "base": step_base,
    "learn": step_learn,
    "past-papers": step_past_papers,
    "question-bank": step_question_bank,
    "knowledge-base": step_knowledge_base,
    "admin": step_admin,
}


async def run(args: argparse.Namespace) -> int:
    chosen = [s for s in STEPS if (not args.only or s in args.only) and s not in args.skip]
    for name in chosen:
        print(f"\n=== {name}")
        try:
            await STEPS[name](args)
        except StepFailed as exc:
            print(f"FAILED: {name}: {exc}", file=sys.stderr)
            print("Fix it and run the same command again (finished steps are not repeated).")
            return 1
    print(f"\nDone: {', '.join(chosen)}.")
    for warning in WARNINGS:
        print(f"WARNING: {warning}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed a fresh customer database (safe to run again)."
    )
    parser.add_argument("--admin-email", help="make this (signed-in once) user an admin")
    parser.add_argument("--only", nargs="+", choices=list(STEPS), default=[], metavar="STEP")
    parser.add_argument("--skip", nargs="+", choices=list(STEPS), default=[], metavar="STEP")
    parser.add_argument("--questions-dir", type=Path, default=QUESTIONS_DIR)
    parser.add_argument("--rag-dir", type=Path, default=RAG_DIR)
    parser.add_argument(
        "--include-samples", action="store_true", help="also ingest our sample_* documents"
    )
    return parser.parse_args(argv)


def main() -> None:
    raise SystemExit(asyncio.run(run(parse_args())))


if __name__ == "__main__":
    main()
