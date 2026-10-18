# `content` module

| | |
|---|---|
| **Owner** | Samni |
| **Purpose** | Topic notes, student uploads + AI summaries, and the personal library. |
| **Tables** | `notes`, `uploads`, `summaries`, `library_items` |
| **Jira epic** | BRN-E04 Notes & Content *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/content` (tasks: `feature/content/BRN-xx-short-name`) |

## Planned endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/topics/{id}/notes` | Approved notes for a topic (full + short) |
| POST | `/api/v1/uploads` | Upload a file -> creates SUMMARIZE_UPLOAD job |
| GET | `/api/v1/uploads/{id}` | Upload status + summary |
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
