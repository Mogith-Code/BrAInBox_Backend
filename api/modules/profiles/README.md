# `profiles` module

| | |
|---|---|
| **Owner** | Mogith |
| **Purpose** | Student profile, including the 3-step onboarding **profile setup** (stream + subject, goal, availability). |
| **Tables** | `student_profiles` |
| **Branch** | `feature/profiles/<short-name>` (this work: `feature/profiles/onboarding-setup`) |

## Endpoints (all need a registered user)

| Method & path | Request | Response | Errors |
|---|---|---|---|
| `GET /api/v1/profile/options` | – | streams, subjects (Biology available; Chemistry, Physics `available: false`), `exam_years`, `target_grades`, `preferred_times` | – |
| `GET /api/v1/profile` | – | `ProfileOut` (all `null` until something is saved) | – |
| `PATCH /api/v1/profile` | any subset of `{stream, subject, exam_year, target_grade, confidence, study_days, hours_per_day, preferred_time}`; `null` clears a field | `ProfileOut` | `VALIDATION_ERROR` (422), `STREAM_NOT_AVAILABLE`, `SUBJECT_NOT_AVAILABLE`, `INVALID_EXAM_YEAR` |
| `POST /api/v1/profile/complete` | – | `ProfileOut` with `profile_completed: true` | `PROFILE_INCOMPLETE` (+ `missing: [...]`) |

`ProfileOut`:
```json
{"stream": "bio_science", "subject": "biology", "exam_year": 2027, "target_grade": "A",
 "confidence": 50, "study_days": ["mon","tue","thu","sat","sun"], "hours_per_day": 2.0,
 "preferred_time": "evening", "weekly_hours": 10.0, "profile_completed": false}
```

Validation:
- `confidence` is 0–100.
- `hours_per_day` is 0.5–6 in 0.5 steps.
- `study_days` must be at least one of `mon`…`sun`; they come back sorted Mon→Sun with no duplicates.
- `target_grade` is A, B or C.
- `preferred_time` is `morning`, `evening` or `night`.
- `exam_year` must be one of `exam_years`: this year plus the next two, so the list moves on by itself each year.
- `weekly_hours = hours_per_day × number of study days` (the app shows "~10 hours a week").

## Used by other modules (service functions)

| Function | Used by |
|---|---|
| `get_onboarding_flags(user_id)` | auth → `UserOut.onboarding` |
| `mark_diagnostic_skipped(user_id)` | quizzes → `POST /diagnostic/skip` |
| `get_study_settings(user_id)` | home → days to exam, today's plan |

Tests: `tests/api/test_profiles.py`.
