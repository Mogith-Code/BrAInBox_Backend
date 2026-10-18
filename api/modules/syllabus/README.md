# `syllabus` module

| | |
|---|---|
| **Owner** | Keshomigha |
| **Purpose** | Read-only syllabus tree for students: units -> topics -> concepts. |
| **Tables** | `units`, `topics`, `concepts` |
| **Jira epic** | BRN-E03 Syllabus *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/syllabus` (tasks: `feature/syllabus/BRN-xx-short-name`) |

## Planned endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/units` | All 10 units |
| GET | `/api/v1/units/{id}/topics` | Topics of a unit |
| GET | `/api/v1/topics/{id}` | One topic with its concepts |

Placeholder right now: `GET /api/v1/syllabus/status` → `{"module": "syllabus", "status": "todo"}` (needs login).

## Files

| File | What goes in it |
|---|---|
| `router.py` | HTTP endpoints only (validate, check role, call service) |
| `schemas.py` | Pydantic request/response models |
| `service.py` | Business logic |
| `repository.py` | All SQL queries for this module |

Models live in `shared/db/models/`. Call other modules through their `service.py`, never their `repository.py`.
Tests: `tests/api/test_syllabus.py`.
