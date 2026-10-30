# `performance` module

| | |
|---|---|
| **Owner** | Keshomigha |
| **Purpose** | Insights for students: mistakes, mastery per concept, weak areas. |
| **Tables** | `mistakes`, `concept_mastery` (topic insights only *read* `attempts`, `responses`, `questions`, `mcq_options`, `topics`, `units`, `misconceptions`, `model_answers`, `resources`) |
| **Jira epic** | BRN-E12 Performance Insights *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/performance` (tasks: `feature/performance/BRN-xx-short-name`) |

## Implemented so far (used by quizzes and home)

| Service function | What it does |
|---|---|
| `record_unit_mastery(user_id, {unit_id: mastery}, source)` | adds a snapshot per unit to `unit_mastery` (history, never updated) |
| `current_unit_mastery(user_id)` | newest mastery per unit |
| `unit_mastery_week_ago(user_id)` | newest mastery per unit older than 7 days (weekly change) |
| `record_study_activity(user_id)` | marks today (Sri Lanka date) in `study_activity` |
| `get_streak(user_id)` | consecutive study days ending today or yesterday |

New tables in migration `0002`: `unit_mastery`, `study_activity`.

## Endpoints

| Method | Path | Status | Description |
|---|---|---|---|
| GET | `/api/v1/insights/topics` | ✅ done | My topic-wise MCQ scores, grades, weak topics and feedback. `?attempt_id=` limits it to one attempt |
| GET | `/api/v1/insights/summary` | planned | Overall progress |
| GET | `/api/v1/insights/units` | planned | Mastery per unit |
| GET | `/api/v1/insights/concepts` | planned | Weakest concepts |
| GET | `/api/v1/mistakes` | planned | My mistakes (filter by type/unit) |
| - | (service) | planned | record_mistake() and update_mastery() called by quizzes/exams/evaluation |

Placeholder: `GET /api/v1/performance/status` → `{"module": "performance", "status": "todo"}` (needs login).

## Grade bands (`grading.py`)

The **only** place thresholds are defined. They are project-configured A/L-style boundaries, not verified
official exam rules, so a grade is a practice indicator, never an official exam grade.

| Grade | Label | Percent | Topic status |
|---|---|---|---|
| A | Distinction Pass | 75 – 100 | `strong` |
| B | Very Good Pass | 65 – < 75 | `good` |
| C | Credit Pass | 55 – < 65 | `developing` |
| S | Ordinary/Simple Pass | 35 – < 55 | `weak` |
| F | Fail | 0 – < 35 | `very_weak` |

`MIN_QUESTIONS_FOR_RELIABLE_RESULT = 5`: a topic with fewer valid answers is `insufficient_data` (its
provisional percent/grade is shown, but it is never listed as a weak topic). Exams uses the same rule for
its per-paper `weak_topics` through `service.is_weak_topic_percent`.

## How topic insights are calculated

1. Read the student's MCQ `responses` from **their own** attempts with status `submitted`/`graded`.
   Another student's `attempt_id` → 403, unknown → 404.
2. Duplicates: one answer per question per attempt (the latest). The same question in two attempts counts twice.
3. **Valid attempted** = an option of that question was selected and `is_correct` is stored. Unanswered
   questions are counted separately; anything else is `excluded`.
4. `Topic score (%) = correct / valid attempted × 100` (2 decimals). A topic with no valid answers has
   `percent = null` and status `not_attempted`, never 0 %.
5. Topics are ranked lowest score first. `weak_topics` = reliable topics graded S or F.
6. `overall` is the same formula over all topics and is reported separately from topic scores.
7. Feedback per topic is template text built from these numbers only, plus stored content: up to 5 wrongly
   answered questions with their approved model answer (or question explanation), misconceptions linked to
   the wrong options the student actually chose, and approved resources for topics below grade B.

## Files

| File | What goes in it |
|---|---|
| `router.py` | HTTP endpoints only (validate, check role, call service) |
| `schemas.py` | Pydantic request/response models |
| `grading.py` | Grade bands and the minimum sample size |
| `service.py` | Business logic (scoring and feedback are pure functions) |
| `repository.py` | All SQL queries for this module |

Models live in `shared/db/models/`. Call other modules through their `service.py`, never their `repository.py`.
Tests: `tests/api/test_performance.py`.
