# `profiles` module

| | |
|---|---|
| **Owner** | Mogith |
| **Purpose** | Student profile details (school, district, exam year, avatar). |
| **Tables** | `student_profiles` |
| **Jira epic** | BRN-E02 Student Profile *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/profiles` (tasks: `feature/profiles/BRN-xx-short-name`) |

## Planned endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/profile` | My profile |
| PATCH | `/api/v1/profile` | Update my profile |

Placeholder right now: `GET /api/v1/profiles/status` → `{"module": "profiles", "status": "todo"}` (needs login).

## Files

| File | What goes in it |
|---|---|
| `router.py` | HTTP endpoints only (validate, check role, call service) |
| `schemas.py` | Pydantic request/response models |
| `service.py` | Business logic |
| `repository.py` | All SQL queries for this module |

Models live in `shared/db/models/`. Call other modules through their `service.py`, never their `repository.py`.
Tests: `tests/api/test_profiles.py`.
