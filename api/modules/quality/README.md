# `quality` module

| | |
|---|---|
| **Owner** | Udith |
| **Purpose** | Question quality: student reports, AI/human review queue, question stats. |
| **Tables** | `question_reviews`, `question_reports`, `question_stats` |
| **Jira epic** | BRN-E09 Question Quality *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/quality` (tasks: `feature/quality/BRN-xx-short-name`) |

## Planned endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/questions/{id}/report` | Report a wrong question |
| - | (service) | Review-queue logic used by admin/questions_admin.py |

Placeholder right now: `GET /api/v1/quality/status` → `{"module": "quality", "status": "todo"}` (needs login).

## Files

| File | What goes in it |
|---|---|
| `router.py` | HTTP endpoints only (validate, check role, call service) |
| `schemas.py` | Pydantic request/response models |
| `service.py` | Business logic |
| `repository.py` | All SQL queries for this module |

Models live in `shared/db/models/`. Call other modules through their `service.py`, never their `repository.py`.
Tests: `tests/api/test_quality.py`.
