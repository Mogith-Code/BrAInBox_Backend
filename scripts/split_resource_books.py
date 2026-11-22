"""Split the NIE Biology resource books into one PDF per unit, ready for the knowledge base.

    python scripts/split_resource_books.py --books "C:/Users/User/Downloads" --out data/rag_sources

One file per unit lets the import tag every passage with its unit (the file name starts with
"unitN"). The output folders are ignored by Git: NEVER commit these books, they are copyrighted.
Safe to re-run: a file that already exists is left alone.
"""

import argparse
import shutil
import sys
from pathlib import Path

import pypdfium2

GRADE_12 = "Grade 12 Biology Resource Book English F.pdf"
GRADE_13_5_6 = "Grade 13 Biology Resource Book Unit 5 Unit 6 English F.pdf"
GRADE_13_7_8 = "Grade 13 Biology Resource Book Unit 7 Unit 8 English F.pdf"
GRADE_13_9_10 = "Grade 13 Biology Resource Book Unit 9 Unit 10 English F.pdf"
PRACTICAL_HANDBOOK = "eALOM Biology Practical Handbook.pdf"

# (book, first PDF page, last PDF page, output name). Page numbers start at 1 and were checked
# against each book's contents page and unit title pages.
UNIT_PAGES = [
    (GRADE_12, 9, 13, "unit01_introduction_to_biology.pdf"),
    (GRADE_12, 14, 79, "unit02_chemical_and_cellular_basis.pdf"),
    (GRADE_12, 80, 114, "unit03_evolution_and_diversity.pdf"),
    (GRADE_12, 115, 163, "unit04_plant_form_and_function.pdf"),
    (GRADE_12, 164, 243, "unit05_animal_form_and_function_part1.pdf"),
    (GRADE_13_5_6, 8, 95, "unit05_animal_form_and_function_part2.pdf"),
    (GRADE_13_5_6, 96, 138, "unit06_genetics.pdf"),
    (GRADE_13_7_8, 9, 69, "unit07_molecular_biology.pdf"),
    (GRADE_13_7_8, 70, 113, "unit08_environmental_biology.pdf"),
    (GRADE_13_9_10, 8, 44, "unit09_microbiology.pdf"),
    (GRADE_13_9_10, 45, 74, "unit10_applied_biology.pdf"),
]


def split_book(source: Path, first: int, last: int, target: Path) -> None:
    """Copy pages first..last (1-based) of `source` into a new PDF."""
    book = pypdfium2.PdfDocument(str(source))
    part = pypdfium2.PdfDocument.new()
    try:
        part.import_pages(book, list(range(first - 1, last)))
        temporary = target.with_suffix(".tmp")
        with temporary.open("wb") as file:
            part.save(file)
        temporary.replace(target)  # a stopped run never leaves half a PDF
    finally:
        part.close()
        book.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--books", type=Path, required=True, help="Folder with the original PDFs")
    parser.add_argument("--out", type=Path, default=Path("data/rag_sources"))
    args = parser.parse_args()

    needed = {row[0] for row in UNIT_PAGES} | {PRACTICAL_HANDBOOK}
    missing = sorted(name for name in needed if not (args.books / name).is_file())
    if missing:
        print("Missing books:\n  " + "\n  ".join(missing))
        return 1

    notes = args.out / "approved_notes"
    guides = args.out / "teacher_guides"
    notes.mkdir(parents=True, exist_ok=True)
    guides.mkdir(parents=True, exist_ok=True)

    for book, first, last, name in UNIT_PAGES:
        target = notes / name
        if target.exists():
            print(f"  already there  {name}")
            continue
        split_book(args.books / book, first, last, target)
        print(f"  created        {name} ({last - first + 1} pages)")

    handbook = guides / "practical_handbook.pdf"
    if not handbook.exists():
        shutil.copy2(args.books / PRACTICAL_HANDBOOK, handbook)
    print("  ready          practical_handbook.pdf")
    return 0


if __name__ == "__main__":
    sys.exit(main())
