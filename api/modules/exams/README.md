# `exams` module

| | |
|---|---|
| **Owner** | Udith |
| **Purpose** | Full papers (past papers and AI-built model papers) and timed attempts. |
| **Tables** | `papers`, `paper_questions`, `attempts`, `responses` |
| **Jira epic** | BRN-E08 Exams & Past Papers *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/exams` (tasks: `feature/exams/BRN-xx-short-name`) |

## Planned endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/papers` | List papers |
| GET | `/api/v1/papers/{id}` | One paper |
| POST | `/api/v1/papers/generate` | Build a model paper -> BUILD_PAPER job |
| POST | `/api/v1/attempts` | Start an attempt |
| GET | `/api/v1/attempts/{id}` | Attempt with answers |
| POST | `/api/v1/attempts/{id}/submit` | Submit an attempt |

Placeholder right now: `GET /api/v1/exams/status` → `{"module": "exams", "status": "todo"}` (needs login).

## Files

| File | What goes in it |
|---|---|
| `router.py` | HTTP endpoints only (validate, check role, call service) |
| `schemas.py` | Pydantic request/response models |
| `service.py` | Business logic |
| `repository.py` | All SQL queries for this module |

Models live in `shared/db/models/`. Call other modules through their `service.py`, never their `repository.py`.
Tests: `tests/api/test_exams.py`.
