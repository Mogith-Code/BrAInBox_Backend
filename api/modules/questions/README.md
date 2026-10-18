# `questions` module

| | |
|---|---|
| **Owner** | Udith |
| **Purpose** | Question bank: questions, MCQ options and misconceptions (read side for students). |
| **Tables** | `questions`, `mcq_options`, `misconceptions`, `question_concepts` |
| **Jira epic** | BRN-E06 Question Bank *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/questions` (tasks: `feature/questions/BRN-xx-short-name`) |

## Planned endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/questions/{id}` | One question with options (no answer key) |
| GET | `/api/v1/topics/{id}/questions` | Practice questions for a topic |
| POST | `/api/v1/questions/{id}/explain` | Explain an MCQ answer (sync AI call) |

Placeholder right now: `GET /api/v1/questions/status` → `{"module": "questions", "status": "todo"}` (needs login).

## Files

| File | What goes in it |
|---|---|
| `router.py` | HTTP endpoints only (validate, check role, call service) |
| `schemas.py` | Pydantic request/response models |
| `service.py` | Business logic |
| `repository.py` | All SQL queries for this module |

Models live in `shared/db/models/`. Call other modules through their `service.py`, never their `repository.py`.
Tests: `tests/api/test_questions.py`.
