# `evaluation` module

| | |
|---|---|
| **Owner** | Keshomigha |
| **Purpose** | Estimate marks + feedback for structured/essay answers (typed or handwritten). |
| **Tables** | `evaluations` |
| **Jira epic** | BRN-E10 Answer Evaluation *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/evaluation` (tasks: `feature/evaluation/BRN-xx-short-name`) |

## Planned endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/evaluations` | Evaluate a typed answer -> EVALUATE_ANSWER job |
| POST | `/api/v1/evaluations/ocr` | Upload a handwritten answer photo -> OCR_ANSWER job |
| GET | `/api/v1/evaluations/{id}` | Result: estimated marks, matched points, feedback |

## Account delete / data export (called by the auth module)

Used by `DELETE /auth/me` and `GET /auth/me/export` (see `api/modules/auth/README.md`). Nothing is committed here; auth commits once for all modules.

`delete_user_data` deletes the student's evaluations and returns the answer-photo folder `answers/<user_id>/` (also photos that were never marked). `export_user_data` lists the evaluations (photos as Storage paths).

## Files

| File | What goes in it |
|---|---|
| `router.py` | HTTP endpoints only (validate, check role, call service) |
| `schemas.py` | Pydantic request/response models |
| `service.py` | Business logic |
| `repository.py` | All SQL queries for this module |

Models live in `shared/db/models/`. Call other modules through their `service.py`, never their `repository.py`.
Tests: `tests/api/test_evaluation.py`.
