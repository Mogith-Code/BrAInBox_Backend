"""Ingestion helpers ported from Udith's ingest_pdfs.py: NIE watermark removal, unit from file name."""

import pytest

from ai_service.rag.ingestion.cleaner import clean_text
from ai_service.rag.ingestion.pipeline import unit_number_from_filename


def test_nie_watermarks_and_headers_are_removed():
    page = (
        "© 2018 National Institute of Education. All Rights Reserved.\n"
        "G.C.E. (Advanced Level) Biology Resource Book\n"
        "• Mitochondria produce ATP.\n"
        "* Markdown bullets are kept."
    )
    assert clean_text(page) == "Mitochondria produce ATP.\n* Markdown bullets are kept."


@pytest.mark.parametrize(
    ("name", "unit"),
    [
        ("unit2_chemical_cellular_basis_of_life.pdf", 2),
        ("Unit-10 Applied Biology.pdf", 10),
        ("unit1_unit-01.pdf", 1),
        ("unit07_molecular.pdf", 7),
        ("units_overview.pdf", None),
        ("sample_cell_transport.md", None),
        ("unit123.pdf", None),
    ],
)
def test_unit_number_from_filename(name, unit):
    assert unit_number_from_filename(name) == unit
