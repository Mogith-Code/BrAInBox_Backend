# `jobs` module

| | |
|---|---|
| **Owner** | shared |
| **Purpose** | Status of long-running AI jobs (the app polls this). |
| **Tables** | `ai_jobs` |
| **Jira epic** | BRN-E15 Platform *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/jobs` (tasks: `feature/jobs/BRN-xx-short-name`) |

## Planned endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/jobs/{id}` | Job status + result (only the requester or an admin) |

Placeholder right now: `GET /api/v1/jobs/status` → `{"module": "jobs", "status": "todo"}` (needs login).

## Files

| File | What goes in it |
|---|---|
| `router.py` | HTTP endpoints only (validate, check role, call service) |
| `schemas.py` | Pydantic request/response models |
| `service.py` | Business logic |
| `repository.py` | All SQL queries for this module |

Models live in `shared/db/models/`. Call other modules through their `service.py`, never their `repository.py`.
Tests: `tests/api/test_jobs.py`.
