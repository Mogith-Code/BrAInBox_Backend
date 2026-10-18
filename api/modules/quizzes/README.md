# `quizzes` module

| | |
|---|---|
| **Owner** | Udith |
| **Purpose** | Short quizzes and the diagnostic test: start, answer, see results. |
| **Tables** | `papers`, `paper_questions`, `attempts`, `responses` |
| **Jira epic** | BRN-E07 Quizzes & Diagnostic *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/quizzes` (tasks: `feature/quizzes/BRN-xx-short-name`) |

## Planned endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/quizzes` | Start a quiz for a topic/unit |
| GET | `/api/v1/quizzes/{id}` | Quiz with questions |
| POST | `/api/v1/quizzes/{id}/responses` | Submit answers |
| GET | `/api/v1/quizzes/{id}/results` | Score + explanations |
| POST | `/api/v1/quizzes/diagnostic` | Start the diagnostic test |

Placeholder right now: `GET /api/v1/quizzes/status` → `{"module": "quizzes", "status": "todo"}` (needs login).

## Files

| File | What goes in it |
|---|---|
| `router.py` | HTTP endpoints only (validate, check role, call service) |
| `schemas.py` | Pydantic request/response models |
| `service.py` | Business logic |
| `repository.py` | All SQL queries for this module |

Models live in `shared/db/models/`. Call other modules through their `service.py`, never their `repository.py`.
Tests: `tests/api/test_quizzes.py`.
