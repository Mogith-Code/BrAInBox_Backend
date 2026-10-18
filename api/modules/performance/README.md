# `performance` module

| | |
|---|---|
| **Owner** | Keshomigha |
| **Purpose** | Insights for students: mistakes, mastery per concept, weak areas. |
| **Tables** | `mistakes`, `concept_mastery` |
| **Jira epic** | BRN-E12 Performance Insights *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/performance` (tasks: `feature/performance/BRN-xx-short-name`) |

## Planned endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/insights/summary` | Overall progress |
| GET | `/api/v1/insights/units` | Mastery per unit |
| GET | `/api/v1/insights/concepts` | Weakest concepts |
| GET | `/api/v1/mistakes` | My mistakes (filter by type/unit) |
| - | (service) | record_mistake() and update_mastery() called by quizzes/exams/evaluation |

Placeholder right now: `GET /api/v1/performance/status` → `{"module": "performance", "status": "todo"}` (needs login).

## Files

| File | What goes in it |
|---|---|
| `router.py` | HTTP endpoints only (validate, check role, call service) |
| `schemas.py` | Pydantic request/response models |
| `service.py` | Business logic |
| `repository.py` | All SQL queries for this module |

Models live in `shared/db/models/`. Call other modules through their `service.py`, never their `repository.py`.
Tests: `tests/api/test_performance.py`.
