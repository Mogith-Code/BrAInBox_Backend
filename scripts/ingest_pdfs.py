import json
import re
import sys
from pathlib import Path

import chromadb
import pymupdf                   # PyMuPDF
import pytesseract
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = ROOT / "app" / "data" / "source"
CACHE_DIR = ROOT / "app" / "data" / "ocr_cache"
DB_PATH = ROOT / "app" / "data" / "chroma_db"
COLLECTION = "biology_syllabus"

TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if Path(TESSERACT_CMD).exists():
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

# ------------------------------------------------------------------
# EDIT THIS: file name -> (unit number, unit name)
# ------------------------------------------------------------------
SOURCES = {
    "unit1_unit-01.pdf": (1, "Introduction to Biology"),
    "unit2_chemical_cellular_basis_of_life.pdf": (2, "Chemical and Cellular Basis of Life"),
    "unit3_evolution-and-diversity-of-organisms.pdf": (3, "Evolution and Diversity of Organisms"),
    "unit4_plant-form-and-function.pdf": (4, "Plant Form and Function"),
    "unit5_animal-form-and-function.pdf": (5, "Animal Form and Function"),
    "unit6_genetics.pdf": (6, "Genetics"),
    "unit7_molecular-biology-and-recombinant-dna-technology.pdf": (7, "Molecular Biology and Recombinant DNA Technology"),
    "unit8_environmental-biology.pdf": (8, "Environmental Biology"),
    "unit9_microbiology.pdf": (9, "Microbiology"),
    "unit10_applied-biology.pdf": (10, "Applied Biology"),
}


def get_unit_info(filename: str):
    if filename in SOURCES:
        return SOURCES[filename]
    m = re.match(r"unit(\d+)_(.+)\.pdf", filename, re.IGNORECASE)
    if m:
        unit_no = int(m.group(1))
        unit_name = m.group(2).replace("-", " ").replace("_", " ").title()
        return (unit_no, unit_name)
    return None

CHUNK_WORDS = 300       # same as Unit 2
OVERLAP = 50

# Watermark / running header text, removed from every page BEFORE chunking
JUNK = [
    re.compile(r"©?\s*2018\s+National\s+Institute\s+of\s+Education\W*\s*All\s+Rights\s+Reserved\W*", re.I),
    re.compile(r"G\W*C\W*E\W*\(?\s*Advanced\s+Level\s*\)?\s*Biology\s+Resource\s+Book", re.I),
]


def clean(text: str) -> str:
    text = re.sub(r"-\n(\w)", r"-\1", text)          # line-end hyphen: keep the hyphen, join the lines
    for p in JUNK:
        text = p.sub(" ", text)
    text = re.sub(r"(?m)^\s*[¢•*]\s+", "", text)     # OCR bullet marks at the start of a line
    return re.sub(r"\s+", " ", text).strip()


def read_pages(pdf_path: Path) -> list:
    """Text of every page. Scanned pages use OCR. Result is cached on disk."""
    cache = CACHE_DIR / f"{pdf_path.stem}.json"
    if cache.exists():
        print("  using OCR cache", flush=True)
        return json.loads(cache.read_text(encoding="utf-8"))

    doc = pymupdf.open(pdf_path)
    pages = []
    for i, page in enumerate(doc, start=1):
        text = page.get_text() or ""
        if len(text.split()) < 30:                   # scanned page -> OCR
            pix = page.get_pixmap(dpi=200)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            text = pytesseract.image_to_string(img, lang="eng")
        pages.append(text)
        print(f"  page {i}/{len(doc)}", end="\r", flush=True)
    print(flush=True)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
    return pages


def make_chunks(pages: list, unit_no: int, unit: str, source: str) -> list:
    words = []                                       # (word, page number)
    for page_no, text in enumerate(pages, start=1):
        for w in clean(text).split(" "):
            if w:
                words.append((w, page_no))

    stem = Path(source).stem[:25]
    chunks = []
    step = CHUNK_WORDS - OVERLAP
    for i, start in enumerate(range(0, len(words), step)):
        piece = words[start:start + CHUNK_WORDS]
        if len(piece) < 60:                          # tiny tail is already inside the overlap
            break
        chunks.append({
            "id": f"U{unit_no}-{stem}-{i + 1:04d}",
            "text": " ".join(w for w, _ in piece),
            "meta": {
                "unit_no": unit_no,
                "unit": unit,
                "source": source,
                "page_start": piece[0][1],
                "page_end": piece[-1][1],
            },
        })
    return chunks


def main():
    if len(sys.argv) > 1:
        targets = sys.argv[1:]
    else:
        pdf_files = sorted(
            SOURCE_DIR.glob("*.pdf"),
            key=lambda p: [int(x) if x.isdigit() else x for x in re.split(r'(\d+)', p.name)]
        )
        targets = [f.name for f in pdf_files] if pdf_files else list(SOURCES)

    client = chromadb.PersistentClient(path=str(DB_PATH))
    collection = client.get_collection(COLLECTION)
    print("Chunks before:", collection.count(), flush=True)

    for name in targets:
        info = get_unit_info(name)
        if not info:
            print(f"SKIP (cannot determine unit info): {name}", flush=True)
            continue
        unit_no, unit = info
        pdf = SOURCE_DIR / name
        if not pdf.exists():
            print(f"SKIP (file not found): {name}", flush=True)
            continue

        print(f"\nReading {name}  (Unit {unit_no}: {unit})", flush=True)
        pages = read_pages(pdf)
        empty = [i for i, p in enumerate(pages, 1) if len(p.split()) < 20]
        if empty:
            print(f"  note: pages with almost no text (diagrams?): {empty}", flush=True)

        chunks = make_chunks(pages, unit_no, unit, name)
        if not chunks:
            print("  no chunks created, check the PDF / OCR", flush=True)
            continue

        collection.delete(where={"source": name})    # safe to re-run
        for i in range(0, len(chunks), 100):
            batch = chunks[i:i + 100]
            collection.upsert(
                ids=[c["id"] for c in batch],
                documents=[c["text"] for c in batch],
                metadatas=[c["meta"] for c in batch],
            )
        print(f"  done: {len(pages)} pages -> {len(chunks)} chunks", flush=True)

    print("\nChunks after:", collection.count(), flush=True)


if __name__ == "__main__":
    main()