# `recommendations` module

| | |
|---|---|
| **Owner** | Udith |
| **Purpose** | Recommended resources (incl. YouTube) and personal study plans. |
| **Tables** | `resources`, `recommendations`, `study_plans`, `plan_items` |
| **Jira epic** | BRN-E13 Recommendations & Study Plan *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/recommendations` (tasks: `feature/recommendations/BRN-xx-short-name`) |

## Planned endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/recommendations` | My recommendations |
| POST | `/api/v1/recommendations/{id}/dismiss` | Hide one |
| GET | `/api/v1/study-plan` | My active study plan |
| POST | `/api/v1/study-plan` | Create / regenerate a plan |
| PATCH | `/api/v1/study-plan/items/{id}` | Mark an item done |

Placeholder right now: `GET /api/v1/recommendations/status` → `{"module": "recommendations", "status": "todo"}` (needs login).

## Files

| File | What goes in it |
|---|---|
| `router.py` | HTTP endpoints only (validate, check role, call service) |
| `schemas.py` | Pydantic request/response models |
| `service.py` | Business logic |
| `repository.py` | All SQL queries for this module |

Models live in `shared/db/models/`. Call other modules through their `service.py`, never their `repository.py`.
Tests: `tests/api/test_recommendations.py`.
