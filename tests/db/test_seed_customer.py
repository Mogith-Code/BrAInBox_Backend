"""scripts/seed_customer.py fills a fresh database and is safe to run twice."""

import os
import shutil
import subprocess
import sys

import pytest

from tests.db.conftest import REPO_ROOT, alembic
from tests.db.test_seed import row_counts

pytestmark = pytest.mark.db

TABLES = [
    "units",
    "topics",
    "concepts",
    "community_groups",
    "app_config",
    "questions",
    "mcq_options",
    "papers",
    "paper_questions",
    "notes",
    "source_documents",
    "document_chunks",
]


def seed_customer(database_url: str, tmp_path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "DATABASE_URL": database_url,
        "STORAGE_BUCKET": "",
        "LOCAL_STORAGE_DIR": str(tmp_path / "storage"),
    }
    return subprocess.run(
        [sys.executable, "scripts/seed_customer.py", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )


def test_customer_seed_twice_changes_nothing(scratch_db, tmp_path, monkeypatch):
    import tests.db.test_seed as seed_test

    monkeypatch.setattr(seed_test, "TABLES", TABLES)
    questions = tmp_path / "questions"
    questions.mkdir()
    shutil.copy(REPO_ROOT / "data/questions/question_bank.json", questions)
    # A past paper file named like a real one, plus the example file that must be ignored.
    shutil.copy(
        REPO_ROOT / "data/questions/example_past_paper.json", questions / "1990_part_1.json"
    )
    shutil.copy(REPO_ROOT / "data/questions/example_past_paper.json", questions)
    # Only the small sample note: a developer's real (gitignored) books would take many minutes.
    rag_notes = tmp_path / "rag_sources" / "approved_notes"
    rag_notes.mkdir(parents=True)
    shutil.copy(REPO_ROOT / "data/rag_sources/approved_notes/sample_cell_transport.md", rag_notes)
    args = (
        "--questions-dir",
        str(questions),
        "--rag-dir",
        str(tmp_path / "rag_sources"),
        "--include-samples",
    )

    alembic("upgrade head", scratch_db)
    first_run = seed_customer(scratch_db, tmp_path, *args)
    assert first_run.returncode == 0, first_run.stdout[-3000:] + first_run.stderr[-3000:]
    first = row_counts(scratch_db)

    second_run = seed_customer(scratch_db, tmp_path, *args)
    assert second_run.returncode == 0, second_run.stdout[-3000:] + second_run.stderr[-3000:]
    assert row_counts(scratch_db) == first

    assert first["units"] == 10
    assert first["papers"] == 1  # only 1990_part_1.json, never example_past_paper.json
    assert first["paper_questions"] == 2
    assert first["questions"] > 2  # the past paper + the question bank
    assert first["source_documents"] >= 1  # the sample note in data/rag_sources
    assert "Done:" in second_run.stdout


def test_skip_and_only(scratch_db, tmp_path):
    alembic("upgrade head", scratch_db)
    result = seed_customer(scratch_db, tmp_path, "--only", "syllabus", "base")
    assert result.returncode == 0, result.stderr[-3000:]
    assert "=== learn" not in result.stdout
    assert row_counts(scratch_db)["units"] == 10
