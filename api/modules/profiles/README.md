# `profiles` module

| | |
|---|---|
| **Owner** | Mogith |
| **Purpose** | Student profile, including the 3-step onboarding **profile setup** (stream + subject, goal, availability); the **Profile page** (overview + achievements); **Settings > Notifications** and **Settings > Data & privacy**. |
| **Tables** | `student_profiles`, `achievements` (definitions), `user_achievements` (my unlocks + seen flag), `user_settings` (notification + privacy switches) |
| **Branch** | `feature/profiles/<short-name>` (this work: `feature/profiles/onboarding-setup`) |

## Endpoints (all need a registered user)

| Method & path | Request | Response | Errors |
|---|---|---|---|
| `GET /api/v1/profile/options` | – | streams, subjects (Biology available; Chemistry, Physics `available: false`), `exam_years`, `target_grades`, `preferred_times` | – |
| `GET /api/v1/profile` | – | `ProfileOut` (all `null` until something is saved) | – |
| `PATCH /api/v1/profile` | any subset of `{stream, subject, exam_year, target_grade, confidence, study_days, hours_per_day, preferred_time}`; `null` clears a field | `ProfileOut` | `VALIDATION_ERROR` (422), `STREAM_NOT_AVAILABLE`, `SUBJECT_NOT_AVAILABLE`, `INVALID_EXAM_YEAR` |
| `POST /api/v1/profile/complete` | – | `ProfileOut` with `profile_completed: true` | `PROFILE_INCOMPLETE` (+ `missing: [...]`) |
| `GET /api/v1/profile/overview` | – | `ProfileOverviewOut` (the Profile page, below) | – |
| `POST /api/v1/achievements/{id}/seen` | – | 204 | `ACHIEVEMENT_NOT_FOUND` (404: unknown id, or not unlocked by me) |
| `GET /api/v1/settings` | – | `{study_reminders, reminder_time, community_replies}` | – |
| `PATCH /api/v1/settings` | any subset (not `null`) | the full object | `VALIDATION_ERROR` (422: `null`, not a bool, `reminder_time` not 24 h `HH:mm`) |
| `GET /api/v1/privacy` | – | `{personalised_recommendations, improve_ai, show_name_in_community, share_research}` | – |
| `PATCH /api/v1/privacy` | any subset (not `null`) | the full object | `VALIDATION_ERROR` (422) |

`/settings` and `/privacy` are on `settings_router` in `router.py` (its own "Settings" group in `/docs`).

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

## Profile page: `GET /profile/overview`

```json
{"full_name": "Nimal Perera", "stream_label": "Biological Science", "exam_year": 2027, "target_grade": "A",
 "days_to_exam": 261, "streak_days": 7, "questions_answered": 134, "topics_mastered": 3,
 "achievements": [{"id": "streak_7", "title": "7-day streak", "icon": "streak",
                   "description": "Study 7 days in a row.", "unlocked": true,
                   "unlocked_at": "2026-11-20T08:15:00Z", "seen": false, "badge_label": "Streak", "xp": 50}],
 "achievements_total": 6}
```

- Real data only: profile (stream, exam year, grade), streak and answer count from performance, topics mastered
  from mastery.
- `stream_label` is `""` before profile setup. `days_to_exam` is days from today (Asia/Colombo) to the date in
  the `AL_EXAM_DATES` setting (`.env`: `{"2027": "2027-08-09", ...}`); `null` if the year or its date is unknown.
- `achievements`: every active one; unlocked first (newest first), then locked in display order.
  `seen: false` on an unlocked one → the app shows the "Achievement unlocked" pop-up, then calls `.../seen`.

## Achievements

Definitions are rows in `achievements` (seeded by migration `0011`); unlocks are `user_achievements`
(`unlocked_at`, `seen_at`). The rules are in `service.ACHIEVEMENT_RULES`:

| id | icon | Unlocks when | xp |
|---|---|---|---|
| `streak_7` | `streak` | 7 study days in a row | 50 |
| `first_mastery` | `first_mastery` | the first topic is mastered | 50 |
| `unit_fixer` | `unit_fixer` | a unit goes from Weak to Strong | 150 |
| `mcq_100` | `mcq_100` | 100 MCQs answered | 100 |
| `past_paper_pro` | `past_paper_pro` | the first past paper is submitted | 100 |
| `unit_master` | `unit_master` | every topic in a unit is mastered | 200 |

Other modules call `check_achievements(session, user_id, only=...)` after the event (no commit; the caller's commit
saves the unlock). One answer / study action checks only `ACTIVITY_ACHIEVEMENTS` (`streak_7`, `mcq_100`); submitting
a quiz, paper or the diagnostic, or mastering a topic, checks all of them. Unlocking is idempotent.

## Settings and privacy (`user_settings`)

One row per student, created with the defaults on first use:

| Field | Default | Effect |
|---|---|---|
| `study_reminders` | `true` | for a study-reminder sender (none exists yet; it must call `get_notification_settings`) |
| `reminder_time` | `"20:30"` | 24 h `HH:mm`, Sri Lanka time |
| `community_replies` | `true` | `false` → no `community_reply` notification (community module) |
| `personalised_recommendations` | `true` | always `true`; PATCH ignores it |
| `improve_ai` | `true` | stored choice |
| `show_name_in_community` | `true` | `false` → posts and replies show "A/L student" instead of the name |
| `share_research` | `false` | stored choice |

## Used by other modules (service functions)

| Function | Used by |
|---|---|
| `get_onboarding_flags(user_id)` | auth → `UserOut.onboarding` |
| `mark_diagnostic_skipped(user_id)` | quizzes → `POST /diagnostic/skip` |
| `get_study_settings(user_id)` | home → days to exam, today's plan |
| `check_achievements(user_id, only=None)` | quizzes, exams, evaluation, home, learn, recommendations |
| `wants_community_replies(user_id)` | community → reply notifications |
| `users_hiding_name(user_ids)` | community → "A/L student" instead of the author's name |
| `get_notification_settings(user_id)` | a future study-reminder sender |

Tests: `tests/api/test_profiles.py`, `tests/api/test_profile_overview.py` (overview, achievements, settings,
privacy), `tests/api/test_community.py` (hidden names).

## Account delete / data export (called by the auth module)

Used by `DELETE /auth/me` and `GET /auth/me/export` (see `api/modules/auth/README.md`). Nothing is committed here; auth commits once for all modules.

`delete_user_data` deletes the profile, `user_settings` and `user_achievements` (the shared `achievements`
definitions stay). `export_user_data` gives `{profile, settings, privacy, achievements}` (settings / privacy show the
defaults when never changed; `achievements` lists only the unlocked ones).
