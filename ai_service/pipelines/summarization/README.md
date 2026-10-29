# `pipelines/summarization`

| | |
|---|---|
| **Owner** | Samni |
| **Purpose** | Summarise a student's uploaded study material. |
| **Branch** | `feature/summarization` |

| File | What it does | Job type | Uses RAG |
|---|---|---|---|
| `preprocess.py` | Read an uploaded file from storage (PDF), clean the text, check length and language. | - | - |
| `chunker.py` | Split long uploads into parts that fit the LLM context. | - | - |
| `summarize.py` | Topic-based summary of the student's notes, or of approved sources (SCRUM-37). | `SUMMARIZE_UPLOAD` | only without notes |

Called by the api content module (`POST /api/v1/uploads/text` and `/uploads/pdf`).

## Topic-based summaries (`summarize.py`)

```json
{"topic_title": "Osmosis", "text": "...notes...", "topic_id": "...", "unit_title": "Unit 2"}
{"topic_title": "Osmosis", "file_path": "uploads/<user>/<upload>.pdf", "mime_type": "application/pdf"}
```

Only `topic_title` is required.

- **With `file_path`**: the file is loaded with `providers.get_storage()` (Firebase Storage, or the
  local `LOCAL_STORAGE_DIR` folder in dev), its text is extracted with `rag.ingestion.loaders`
  (scanned pages: Tesseract OCR when installed), then it is treated like `text`.
- **With `text`**: the notes are cleaned (`preprocess`) and summarised. Notes longer than 1500 words
  are split (`chunker`), each part is summarised with `summarize_chunk.v1` (up to 3 parts at the same
  time), and the parts are merged.
- **Without both**: approved sources for the topic are retrieved with RAG and summarised with
  `[n]` citations. No sources -> `NoContextError` (we never invent a summary).

Input problems raise a `UserInputError` (`ai_service/errors.py`); `/jobs/run` answers
422 `{"error": {"code", "message"}}` and the api shows the message to the student:

| Code | When |
|---|---|
| `EMPTY_NOTES` | nothing left after cleaning |
| `NO_TEXT_IN_FILE` | a file without readable text (e.g. scanned, no OCR) |
| `NOTES_TOO_LONG` | more than `MAX_INPUT_CHARS` (60,000) characters after cleaning |
| `NOT_ENGLISH` | less than half of the letters are a-z (Sinhala, Tamil...) |
| `UNSUPPORTED_FILE_TYPE` / `UNREADABLE_FILE` | not a PDF / a broken PDF |
| `NO_SOURCES_FOR_TOPIC` | no notes and no approved sources |
| `MISSING_TOPIC_TITLE` | `topic_title` is empty |

The final summary uses `summarize_topic.v1` and is validated as `TopicSummary`. Result:

```json
{"title": "...", "body_md": "...", "key_points": [], "key_terms": [],
 "topic_id": "..." , "source": "notes | rag", "citations": [],
 "prompt_version": "summarization/summarize_topic.v1"}
```

`body_md`, `topic_id` and `prompt_version` match the `summaries` table. Tests: `tests/ai_service/test_summarization.py`.

## Rules

- Call AI only through `ai_service.providers` (`get_llm()`, `get_embedder()`, ...). Never import an SDK here.
- Grounded pipelines use `ai_service.rag.retrieval.retriever.retrieve` + `ai_service.rag.context_builder.build_context`.
  Never query `document_chunks` directly.
- Prompts live in `ai_service/prompts/summarization/` and are versioned (`name.v1.j2`). Return the prompt id with the result.
- Validate LLM output with a schema from `ai_service/schemas/llm_outputs.py` (`generate_json`).
- Tests run with the fake providers (no API keys).
- Never put the student's notes in an error message or a log line (they may contain personal data).
