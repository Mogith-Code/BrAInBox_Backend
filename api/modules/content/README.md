# `content` module

| | |
|---|---|
| **Owner** | Samni |
| **Purpose** | Topic notes, student uploads + AI summaries, and the personal library. |
| **Tables** | `notes`, `uploads`, `summaries`, `library_items` |
| **Jira epic** | BRN-E04 Notes & Content *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/content` (tasks: `feature/content/BRN-xx-short-name`) |

## Implemented endpoints: uploads to summarise

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/uploads/text` | Text notes (JSON) -> `uploads` row + SUMMARIZE_UPLOAD job. **202**, status `queued` |
| POST | `/api/v1/uploads/pdf` | PDF (multipart) -> saved to storage + SUMMARIZE_UPLOAD job. **202**, status `queued` |
| GET | `/api/v1/uploads/{id}` | Upload status + summary (owner or admin) |

Flow: POST answers at once with `status: "queued"`. The job runs in the background
(`service.process_upload`); the app polls GET until `status` is `succeeded` (`summary` filled) or
`failed` (`error` filled). Status values are `shared.enums.JobStatus`, stored in `uploads.processing_status`.

`POST /uploads/text` body:

```json
{"input_type": "text", "title": "Photosynthesis", "text": "...", "topic_id": null,
 "options": {"length": "medium", "format": "bullet_points"}}
```

| Field | Rules |
|---|---|
| `title` | required, 1-200 characters, not blank |
| `text` | required, 1-60,000 characters, not blank (same limit as `MAX_INPUT_CHARS` in the ai_service) |
| `topic_id` | optional; unknown id -> 404 `TOPIC_NOT_FOUND` |
| `options.length` | only `medium` for now (about 400 words) |
| `options.format` | only `bullet_points` for now; unknown option names are rejected |

`POST /uploads/pdf` form fields: `file` (`application/pdf`, at most 10 MB), `title`, optional `topic_id`.
Errors: 413 `FILE_TOO_LARGE`, 415 `UNSUPPORTED_FILE_TYPE`, 422 `EMPTY_FILE`,
503 `STORAGE_NOT_CONFIGURED`. The file is saved at `uploads/<user_id>/<upload_id>.pdf` in Firebase
Storage, or in `LOCAL_STORAGE_DIR` in dev when `STORAGE_BUCKET` is empty. The ai_service extracts the
text (scanned pages need Tesseract, installed in the ai_service Docker image).

Response (all three endpoints):

```json
{"upload_id": "uuid", "input_type": "text", "title": "Photosynthesis", "topic_id": null,
 "status": "succeeded",
 "summary": {"id": "uuid", "body_md": "## ...", "prompt_version": "summarization/summarize_topic.v1",
             "created_at": "..."},
 "error": null, "created_at": "..."}
```

A failed upload has `"status": "failed"`, `"summary": null` and an `error`:

| `error.code` | Meaning | The student should |
|---|---|---|
| `EMPTY_NOTES` | nothing left after cleaning (e.g. only page numbers) | send real notes |
| `NO_TEXT_IN_FILE` | the PDF has no readable text (scanned, no OCR) | paste the text instead |
| `NOTES_TOO_LONG` | more than 60,000 characters (a long PDF) | split the notes |
| `NOT_ENGLISH` | mostly non-Latin letters (e.g. Sinhala, Tamil) | send English notes |
| `UNREADABLE_FILE` | broken PDF | send another file |
| `SUMMARIZATION_FAILED` | anything else: AI down, timeout, invalid AI output | try again later |

The input codes come from `ai_service/pipelines/summarization/preprocess.py` (422 from the ai_service,
passed on by `api/core/ai_client.py` and kept as `"CODE: message"` in `ai_jobs.error`). For
`SUMMARIZATION_FAILED` the real cause is only logged and kept in `ai_jobs.error`.

Text notes are not stored as a file (`uploads.file_path` is empty); the text is kept in the job payload
(`ai_jobs.input`).

## Planned endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/topics/{id}/notes` | Approved notes for a topic (full + short) |
| GET | `/api/v1/library` | My saved items |
| POST | `/api/v1/library` | Save an item |
| DELETE | `/api/v1/library/{id}` | Remove an item |

Placeholder right now: `GET /api/v1/content/status` → `{"module": "content", "status": "todo"}` (needs login).

## Files

| File | What goes in it |
|---|---|
| `router.py` | HTTP endpoints only (validate, check role, call service) |
| `schemas.py` | Pydantic request/response models |
| `service.py` | Business logic |
| `repository.py` | All SQL queries for this module |

Models live in `shared/db/models/`. Call other modules through their `service.py`, never their `repository.py`.
Tests: `tests/api/test_content.py`.
