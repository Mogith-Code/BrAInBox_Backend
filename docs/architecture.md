# Architecture

```
 brainbox-mobile repo                         brainbox-backend repo (this one)
┌──────────────────────┐   HTTPS + Firebase   ┌──────────────────────────────┐  X-Service-Token  ┌──────────────────────────────┐
│ Flutter mobile app   │ ───── ID token ────▶ │ api/  (public REST, :8000)   │ ────────────────▶ │ ai_service/ (internal, :8001)│
│ Flutter admin portal │                      │ auth, roles, business logic, │   httpx           │ the ONLY code that calls AI  │
└──────────────────────┘                      │ DB writes, jobs              │ ◀──────────────── │ providers/  rag/  pipelines/ │
           │                                  └──────────────┬───────────────┘   job results     └───────┬─────────────┬────┘
           │ Firebase Auth (sign-in)                         │                                         │             │
           ▼                                                 ▼                                         ▼             ▼
   Firebase Auth / Storage ◀──── signed URLs ──── PostgreSQL 15 + pgvector  ◀── document_chunks ──  Gemini, Vision OCR,
                                                    (shared/db/models)                              embeddings, Imagen
```

## Services

| | `api/` | `ai_service/` |
|---|---|---|
| Who calls it | mobile app, admin portal | only `api/core/ai_client.py` |
| Auth | Firebase ID token → `get_current_user`, `require_role("admin")` | shared secret header `X-Service-Token` |
| Talks to AI providers | **never** | yes, only via `providers/` |
| Writes to the DB | yes (all business data) | RAG tables (`source_documents`, `document_chunks`), usage log |
| Port | 8000 | 8001 (not exposed publicly in production) |

`shared/` holds code both services import: settings, enums, branding and the SQLAlchemy models.

## Request flow (sync)

`router.py` (validate + role) → `service.py` (logic) → `repository.py` (SQL) → Postgres.

## AI job flow (async)

1. The client calls, for example, `POST /api/v1/visuals/generate`.
2. The service runs `core/jobs.create_job()`. This writes an `ai_jobs` row with status `queued`.
3. `core/jobs.enqueue_job()` hands the job to a runner. In dev (`JOB_RUNNER=local`) that is FastAPI `BackgroundTasks`. In prod it will be Cloud Tasks (TODO).
4. The runner calls the ai_service `POST /jobs/run`. The ai_service dispatches on `JobType` to a pipeline.
5. The result is stored on the job row. The client polls `GET /api/v1/jobs/{id}`.

Fast AI calls (explain an MCQ, tag a post) skip jobs and go through `POST /sync/*`.

## RAG (Retrieval-Augmented Generation)

A single shared layer, `ai_service/rag/`. The full guide is in `ai_service/rag/README.md`.

- **Sources.** Only admin-approved documents: the NIE syllabus, teacher guides, approved notes and marking schemes.
- **Ingestion.** load → clean → chunk (~500 words, 50 overlap, heading path) → metadata (unit/topic/concept) → embed → store.
  It is idempotent by SHA-256.
- **Retrieval.** Hybrid search: pgvector cosine plus Postgres full-text (`tsvector`), with merged scores and metadata filters.
- **Citations.** `context_builder` numbers the sources `[1]`, `[2]`. Generated content keeps the list of chunks it used, for admin review.
- **Used by.** `notes`, `questions` (generation + reviewer), `evaluation/feedback` and `community/suggested_answer`.
  These pipelines never query `document_chunks` directly.

## Providers and fakes

`ai_service/providers/base.py` defines the Protocols `LLMProvider`, `EmbeddingProvider`, `OCRProvider`, `ImageProvider` and `StorageProvider`.
Each real adapter (Gemini, Vision, Imagen, Firebase Storage) has a deterministic fake in `providers/fakes.py`.
The fakes are used when `USE_FAKE_AI=true` or `GEMINI_API_KEY` is empty. The system starts and the tests run with no keys at all.

## Prompts

Prompts are versioned Jinja2 templates in `ai_service/prompts/<pipeline>/<name>.vN.j2`. A prompt that has shipped is never edited.
Add `vN+1` instead and save the prompt id with the output.

## Errors

Both services return `{"error": {"code": "SOME_CODE", "message": "..."}}`. In the api, raise `AppError` or one of its subclasses (`api/core/errors.py`).
