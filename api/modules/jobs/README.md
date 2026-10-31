# `jobs` module

| | |
|---|---|
| **Owner** | shared |
| **Purpose** | Status of long-running AI jobs (the app polls this). |
| **Tables** | `ai_jobs` |
| **Jira epic** | BRN-E15 Platform *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/jobs` (tasks: `feature/jobs/BRN-xx-short-name`) |

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/jobs/{job_id}` | ✅ Job status + result (only the requester or an admin, else 404 `JOB_NOT_FOUND`) |

`JobOut`: `id, job_type, status (queued | running | succeeded | failed | cancelled), progress (0 or 1),
result (the pipeline's output, e.g. {"visual_id": "..."}), error, error_code, created_at, finished_at`.

`error` is always a sentence a student can read: a pipeline's input error keeps its message (e.g.
`NOT_BIOLOGY`: "I can only draw Biology visuals."), `AI_SERVICE_UNAVAILABLE` says the AI is busy, and any
technical error becomes "Something went wrong while making this. Please try again."

Modules that must save rows when a job succeeds pass `on_success` to `core/jobs.run_job_inline`, so the
rows and status "succeeded" are saved in one commit (see `api/modules/visuals/service.py`).

## Files

| File | What goes in it |
|---|---|
| `router.py` | HTTP endpoints only (validate, check role, call service) |
| `schemas.py` | Pydantic request/response models |
| `service.py` | Business logic |
| `repository.py` | All SQL queries for this module |

Models live in `shared/db/models/`. Call other modules through their `service.py`, never their `repository.py`.
Tests: `tests/api/test_jobs.py`.
