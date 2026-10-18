# `home` module

| | |
|---|---|
| **Owner** | Samni (frontend home owner) |
| **Purpose** | Everything the home dashboard shows (design "B1 Home dashboard"). |
| **Tables** | none of its own: it calls the services of profiles, performance, recommendations, syllabus and quizzes |
| **Branch** | `feature/home/<short-name>` (this work: `feature/home/summary`) |

## Endpoints (need a registered user)

| Method & path | Request | Response | Errors |
|---|---|---|---|
| `GET /api/v1/home/summary` | – | `HomeSummary` | – |
| `PATCH /api/v1/home/plan/{item_id}` | `{done: true\|false}` | the updated plan item | `PLAN_ITEM_NOT_FOUND` (404) |

`HomeSummary`:
```json
{"greeting_name": "Nethmi", "initials": "NP", "streak_days": 12, "days_to_exam": 287,
 "next_best_action": {"type": "revise", "title": "Revise: Dihybrid crosses",
   "reason": "...", "button_label": "Start 10-min revision", "minutes": 10,
   "target": {"unit_code": "6", "topic_id": "uuid"}, "ai_generated": true},
 "todays_plan": {"done": 1, "total": 3, "items": [
   {"id": "uuid", "kind": "recap", "title": "Recap: Dihybrid crosses", "minutes": 10,
    "unit_label": "Unit 6", "topic_id": "uuid", "done": true}]},
 "overall_mastery": 62, "mastery_change_week": 4,
 "continue_learning": [{"topic_id": "uuid", "title": "Cell membrane transport", "unit_code": "2", "progress": 48}]}
```

## How each value is worked out (first version: simple and explainable, no fake numbers)

| Field | Rule | Comes from |
|---|---|---|
| `greeting_name`, `initials` | first name from `full_name` (else the email name); 2 initials | the logged-in user |
| `streak_days` | consecutive study days ending today **or yesterday** (so it isn't "broken" in the morning). A study day = a diagnostic answer or a ticked plan item. 0 for new students. | `performance.get_streak` (`study_activity`) |
| `days_to_exam` | `AL_EXAM_DATES[exam_year] − today` (Sri Lanka date); `null` if the year or its date is unknown. **Real dates TBD.** | `profiles` + setting |
| `next_best_action` | diagnostic not done → "Find your starting point" (`ai_generated: false`); otherwise the **weakest unit** (lowest mastery) and its first topic. `reason` comes from the ai_service (`/sync/next-action`, prompt `home/next_action.v1`); if that fails, a template sentence with `ai_generated: false` | quizzes, performance, syllabus, AI |
| `todays_plan` | 3 tasks (recap 10 min, practice 15, read 5; ×2 at 4 h/day, ×3 at 6 h/day) from the 3 weakest units, created on the first request of the day and saved in `daily_plan_items`. **Empty** on a non-study day or before any mastery exists (no diagnostic yet). | `recommendations.get_today_plan` |
| `overall_mastery` | average of the newest mastery per unit; `null` before any data | `performance` (`unit_mastery`) |
| `mastery_change_week` | that average now − the average from the newest values older than 7 days; 0 without history | `performance` |
| `continue_learning` | up to 5 current topics of the weakest units; `progress` = that unit's mastery (for now) | `syllabus` + `performance` |

Ticking a plan item (`done: true`) also counts as study activity (streak).

## TODO(Samni)
- Cache the AI reason per day (today it's requested on every summary call).
- Use real topic progress (notes read, questions practised) instead of unit mastery for `continue_learning`.
- Use recent mistakes for a more specific `reason` (e.g. "You missed 4 of 5 recently...").

Tests: `tests/api/test_home.py`.
