"""Chunk sizes, overlap and heading metadata."""

import pytest

from ai_service.rag.ingestion.chunker import chunk_text, parse_heading
from ai_service.rag.ingestion.cleaner import clean_pages
from ai_service.rag.ingestion.loaders import PageText


def words(n: int, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def test_chunk_size_never_exceeds_limit():
    chunks = chunk_text(words(1234), chunk_tokens=100, overlap=10)
    assert all(c.token_count <= 100 for c in chunks)
    assert all(c.token_count == len(c.text.split()) for c in chunks)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_consecutive_chunks_overlap():
    chunks = chunk_text(words(300), chunk_tokens=100, overlap=20)
    for previous, current in zip(chunks, chunks[1:], strict=False):
        assert previous.text.split()[-20:] == current.text.split()[:20]


def test_every_word_is_kept():
    chunks = chunk_text(words(250), chunk_tokens=100, overlap=10)
    seen = {w for c in chunks for w in c.text.split()}
    assert seen == set(words(250).split())


def test_heading_path_is_recorded_and_sections_do_not_mix():
    text = (
        "# Unit 2 Cells\n\n"
        "## Cell membrane\n" + words(30, "m") + "\n\n"
        "### Active transport\n" + words(30, "a") + "\n\n"
        "## Organelles\n" + words(30, "o")
    )
    chunks = chunk_text(text, chunk_tokens=100, overlap=10)
    assert [c.heading_path for c in chunks] == [
        "Unit 2 Cells > Cell membrane",
        "Unit 2 Cells > Cell membrane > Active transport",
        "Unit 2 Cells > Organelles",
    ]
    assert chunks[1].text.split()[0] == "a0"  # no overlap across sections


def test_numbered_headings():
    assert parse_heading("2.3 Cell membrane and transport") == (
        2,
        "2.3 Cell membrane and transport",
    )
    assert parse_heading("## Osmosis") == (2, "Osmosis")
    assert parse_heading("Osmosis is the diffusion of water.") is None


def test_invalid_overlap_is_rejected():
    with pytest.raises(ValueError):
        chunk_text("text", chunk_tokens=10, overlap=10)


def test_cleaner_removes_page_numbers_and_repeated_headers():
    pages = [
        PageText(page=i, text=f"NIE Biology Teacher Guide\nContent of page {i}\nPage {i} of 4")
        for i in range(1, 5)
    ]
    cleaned = clean_pages(pages)
    assert cleaned[0].text == "Content of page 1"
