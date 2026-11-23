"""Government book pages in the Notes tab: finding the topic's page and rendering it."""

import uuid

import pypdfium2
import pytest

from api.modules.learn import official_notes
from api.modules.learn.official_notes import Passage, book_title, find_start_page

BOOK = uuid.uuid4()
PASSAGES = [
    Passage(BOOK, 1, "Introduction to the unit and its aims."),
    Passage(BOOK, 4, "The Scope and importance of   biology in daily life."),
    Passage(BOOK, 7, "Organisation of cells, tissues and whole organisms."),
]


def test_finds_the_exact_title_even_with_odd_spacing():
    start = find_start_page("Scope and importance of biology", PASSAGES)
    assert (start.page, start.exact) == (4, True)


def test_finds_a_topic_by_most_of_its_words():
    start = find_start_page("Organisation of tissues and cells", PASSAGES)
    assert (start.page, start.exact) == (7, True)


def test_unknown_topic_opens_at_the_start_of_the_unit():
    start = find_start_page("Hydroponics", PASSAGES)
    assert (start.document_id, start.page, start.exact) == (BOOK, 1, False)


def test_no_passages():
    assert find_start_page("Anything", []) is None


@pytest.mark.parametrize(
    ("stored", "shown"),
    [
        ("Unit01 Introduction To Biology", "Unit 1: Introduction To Biology"),
        ("Unit10 Applied Biology", "Unit 10: Applied Biology"),
        ("Practical Handbook", "Practical Handbook"),
    ],
)
def test_book_title(stored, shown):
    assert book_title(stored) == shown


@pytest.mark.parametrize("stored", ["../.env", "../../secret.pdf", "data/../.env", "C:/x/book.pdf"])
def test_only_pdfs_inside_the_data_folder_can_be_opened(stored):
    assert official_notes.local_book(stored) is None


def test_renders_a_page_as_jpeg(tmp_path):
    pdf = pypdfium2.PdfDocument.new()
    pdf.new_page(200, 300)
    pdf.new_page(200, 300)
    path = tmp_path / "book.pdf"
    with path.open("wb") as file:
        pdf.save(file)
    pdf.close()

    assert official_notes.page_count(path) == 2
    assert official_notes.render_page(path, 2).startswith(b"\xff\xd8")  # JPEG header
