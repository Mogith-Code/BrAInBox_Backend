# `recommendations` module

| | |
|---|---|
| **Owner** | Udith |
| **Purpose** | Recommended resources (incl. YouTube) and personal study plans. |
| **Tables** | `resources`, `recommendations`, `study_plans`, `plan_items` |
| **Jira epic** | BRN-E13 Recommendations & Study Plan *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/recommendations` (tasks: `feature/recommendations/BRN-xx-short-name`) |

## Implemented so far: today's plan (used by home)

`get_today_plan(...)` creates 3 tasks for today (recap / practice / read) from the weakest units on the first
request of the day and stores them in `daily_plan_items` (done/undone is remembered); `set_plan_item_done(...)`
ticks one. Empty on non-study days. New table in migration `0002`: `daily_plan_items`.

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
