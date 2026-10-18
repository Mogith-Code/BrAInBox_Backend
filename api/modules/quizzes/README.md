# `quizzes` module

| | |
|---|---|
| **Owner** | Udith |
| **Purpose** | Short quizzes and the diagnostic test: start, answer, see results. |
| **Tables** | `papers`, `paper_questions`, `attempts`, `responses` |
| **Jira epic** | BRN-E07 Quizzes & Diagnostic *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/quizzes` (tasks: `feature/quizzes/BRN-xx-short-name`) |

## Diagnostic test (implemented — onboarding "find your starting point")

| Method & path | Request | Response | Errors |
|---|---|---|---|
| `POST /api/v1/diagnostic/start` | – | `{attempt_id, total: 15, minutes: 10, answered, questions: [{id, unit_code, unit_title, stem, options: [{id, label, text}], selected_option_id}]}` — **never** the correct answers; re-calling returns the same unfinished test | `NOT_ENOUGH_QUESTIONS` (409) |
| `POST /api/v1/diagnostic/{attempt_id}/answer` | `{question_id, option_id}` | `{saved: true, answered, total}` (one at a time, so progress survives restarts) | `ATTEMPT_NOT_FOUND`, `ATTEMPT_FINISHED`, `QUESTION_NOT_IN_ATTEMPT`, `OPTION_INVALID` |
| `POST /api/v1/diagnostic/{attempt_id}/submit` | – | `DiagnosticResult` | `ATTEMPT_FINISHED` |
| `POST /api/v1/diagnostic/skip` | – | `{skipped: true}` (sets `onboarding.diagnostic_skipped`) | – |
| `GET /api/v1/diagnostic/result` | – | latest `DiagnosticResult` | `DIAGNOSTIC_NOT_FOUND` (404) |

How it works:
- **Selection**: approved MCQs (well-formed: 2+ options, exactly one correct) whose topic is not `is_outdated`.
  1 per unit, then each extra question goes to the unit furthest below its fair share by `units.exam_weight`
  (1.0 for every unit until real past-paper weights are entered). Shown unit by unit.
- **Storage**: a `papers` row (`paper_type = "diagnostic"`), `paper_questions`, one `attempts` row, `responses`.
- **Mastery per unit** = `round((correct + 0.5) / (asked + 1) × 100)` (pulled towards 50 with few questions);
  status `strong` ≥ 70, `ok` 40–69, `needs_work` < 40. Unanswered = wrong.
- **Saved** as a snapshot in `unit_mastery` (performance module) — the home screen reads it.
- **Summary**: ai_service `/sync/diagnostic-summary` (prompt `diagnostic/summary.v1`); if it fails a template
  sentence is used with `summary_ai_generated: false`. Stored in `attempts.feedback`.
- Each saved answer counts as study activity (streak).

## Planned endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/quizzes` | Start a quiz for a topic/unit |
| GET | `/api/v1/quizzes/{id}` | Quiz with questions |
| POST | `/api/v1/quizzes/{id}/responses` | Submit answers |
| GET | `/api/v1/quizzes/{id}/results` | Score + explanations |
| POST | `/api/v1/quizzes/diagnostic` | Start the diagnostic test |

Placeholder right now: `GET /api/v1/quizzes/status` → `{"module": "quizzes", "status": "todo"}` (needs login).

## Files

| File | What goes in it |
|---|---|
| `router.py` | HTTP endpoints only (validate, check role, call service) |
| `schemas.py` | Pydantic request/response models |
| `service.py` | Business logic |
| `repository.py` | All SQL queries for this module |

Models live in `shared/db/models/`. Call other modules through their `service.py`, never their `repository.py`.
Tests: `tests/api/test_quizzes.py`.
