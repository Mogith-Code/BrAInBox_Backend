# RAG layer (`ai_service/rag/`)

**Owner:** Samni (ingestion + retrieval), with Keshomigha (`shared/db/models/rag.py` + migration).

One shared Retrieval-Augmented Generation layer used by every pipeline that must be grounded in
**admin-approved** sources: the NIE syllabus, teacher guides, approved notes and marking schemes.

```
ingestion/   loaders.py → cleaner.py → chunker.py → metadata.py → pipeline.py
indexing/    embedder.py (providers/embeddings.py)   vector_store.py (pgvector + full-text)
retrieval/   retriever.py (entry point) → hybrid.py (vector + keyword) → reranker.py (placeholder)
context_builder.py   chunks → prompt context with [n] citations
schemas.py           Chunk, RetrievalQuery, RetrievedChunk
```

## How ingestion works

1. **Load** a PDF / DOCX / TXT / Markdown file page by page (`loaders.py`).
2. **Clean** it: drop page numbers and headers/footers repeated on most pages, fix hyphenation and spaces (`cleaner.py`).
3. **Chunk** it into ~500-word pieces with 50 words of overlap. Markdown headings (`#`) and numbered
   headings (`2.3 Cell membrane`) build the `heading_path`; a new heading always starts a new chunk (`chunker.py`).
4. **Attach metadata**: `unit_id` from the document, `topic_id` by matching topic titles in the heading path,
   `concept_id` (TODO) (`metadata.py`).
5. **Embed** each chunk (heading path + text) with the embedding provider: Gemini, or the deterministic fake (`indexing/embedder.py`).
6. **Store** the chunks in `document_chunks`, replacing the document's old chunks in one transaction.
   Postgres fills the `tsv` (full-text) column itself (`indexing/vector_store.py`).

`pipeline.py` is **idempotent**. It keeps the file's SHA-256 in `source_documents.sha256` and skips unchanged
files unless you pass `--force`.

## How retrieval works

```python
from ai_service.rag.retrieval.retriever import retrieve
from ai_service.rag.context_builder import build_context

chunks = await retrieve("active transport", unit_id=unit_id, k=8)
context = build_context(chunks)
# context.text goes into the prompt; context.citations is saved with the output
```

- **Hybrid search.** Retrieval runs a pgvector cosine search and a Postgres full-text search (`websearch_to_tsquery`),
  then merges them: `score = 0.6 × vector + 0.4 × normalised keyword` (`RAG_VECTOR_WEIGHT`).
  Exact Biology terms like "nephron" still match even when the embeddings are fuzzy.
- **Filters**: `unit_id`, `topic_id`, `concept_id` and `source_types`. Only documents with status `ready` are searched.
- **Rule.** Pipelines never query `document_chunks` directly. They always go through `retrieve()`.

## Adding a new source document

**From the CLI (dev):**

1. Put the file in the right folder: `data/rag_sources/{syllabus|teacher_guides|approved_notes|marking_schemes}/`.
   Copyrighted files are **not committed**; `.gitignore` keeps only `.gitkeep`, `README.md` and `sample_*` files.
2. Ingest it:
   ```bash
   python scripts/ingest_documents.py                       # everything in data/rag_sources
   python scripts/ingest_documents.py --path data/rag_sources/approved_notes/cells.md --unit 2
   ```
3. Check it:
   ```bash
   python scripts/rag_search.py --q "active transport" --unit 2   # one search
   python scripts/inspect_rag.py                                  # chunks per unit, leftover watermarks
   python scripts/rag_chat.py --unit 2                            # ask questions in the terminal
   ```

**NIE resource books (Udith's setup).** Name the PDFs `unit<N>_<name>.pdf` (e.g. `unit2_chemical_cellular_basis_of_life.pdf`)
and put them in `data/rag_sources/syllabus/`. The unit is read from the file name. The NIE watermark
("© 2018 National Institute of Education…") and the "Biology Resource Book" running header are removed.
Scanned pages are read with **Tesseract OCR** when it is installed (Docker image: yes; Windows: install it, or set `TESSERACT_CMD`).

**From the admin portal (planned):** `POST /api/v1/admin/rag/documents` uploads the file and creates a
`source_documents` row plus a `RAG_INGEST` job. The ai_service then runs `pipeline.run_job`.

> Use the **same embedder** for ingesting and for searching. Fake vectors and Gemini vectors are not comparable.
> After switching `USE_FAKE_AI`, re-ingest with `--force`.

## Tests

`tests/ai_service/rag/test_chunker.py` covers chunk sizes, overlap and headings.
`test_retriever.py` runs the in-memory store with fake embeddings. Its `db` test runs the full pipeline on Postgres.
