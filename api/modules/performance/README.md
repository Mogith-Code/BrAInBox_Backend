# `performance` module

| | |
|---|---|
| **Owner** | Keshomigha |
| **Purpose** | Insights for students: mistakes, mastery per concept, weak areas. |
| **Tables** | `mistakes`, `concept_mastery`, `unit_mastery`, `study_activity`, `user_topic_progress` (topic insights only *read* `attempts`, `responses`, `questions`, `mcq_options`, `topics`, `units`, `misconceptions`, `model_answers`, `resources`) |
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
| `refresh_topic_progress(user_id)` | recomputes `user_topic_progress` from all finished attempts. Exams and the diagnostic call it on submit today; `after_attempt_marked` (below) runs it too and should replace that call |

New tables in migration `0002`: `unit_mastery`, `study_activity`.

## Endpoints

| Method | Path | Status | Description |
|---|---|---|---|
| GET | `/api/v1/insights/topics` | ✅ done | My topic-wise MCQ scores, grades, weak topics and feedback. `?attempt_id=` limits it to one attempt |
| GET | `/api/v1/insights/summary` | ✅ done | My overview: overall mastery + weekly change, MCQ score, topic levels, streak and study days |
| GET | `/api/v1/insights/units` | ✅ done | My mastery per unit (0-100) with grade, weekly change, strongest / weakest unit |
| POST | `/api/v1/topics/{topic_id}/start` | ✅ done | Mark a topic as started (code or UUID). Safe to repeat; never changes a score or `mastered`. Unknown → 404 `TOPIC_NOT_FOUND` |
| GET | `/api/v1/insights/concepts` | ✅ done | My score per concept (sub-topic), weakest first. Empty until questions are linked to concepts (`linked_answers: 0`) |
| GET | `/api/v1/mistakes` | ✅ done | My wrong MCQ answers, newest first, paged. Filters: `type`, `unit_id`, `status` (`open` / `resolved`) |
| PATCH | `/api/v1/mistakes/{id}` | ✅ done | `{"resolved": true}` = fixed, `false` = open again. Not yours → 404 `MISTAKE_NOT_FOUND` |
| - | (service) `after_attempt_marked()` | ✅ built, ⚠️ **not called yet** | ONE call after marking: mistakes + unit and concept mastery + Learn progress. Exams and quizzes must call it, or the journal stays empty |
| - | (service) `record_mistakes()`, `update_mastery()` | ✅ built | The parts `after_attempt_marked()` runs |

Placeholder: `GET /api/v1/performance/status` → `{"module": "performance", "status": "todo"}` (needs login).

### How topic progress is calculated (Learn screens)

`user_topic_progress` comes from the same topic score as `GET /insights/topics`, so the two screens agree:
`score` is the percent correct over all finished attempts, rounded. `status` is `mastered` for a reliable
grade A and `in_progress` otherwise. `is_weak` is true for a reliable grade S or F. "Reliable" means at
least `MIN_QUESTIONS_FOR_RELIABLE_RESULT` (5) valid answers. A topic with no valid answers, or questions
with no topic (papers by unit), changes nothing. A row whose values didn't change keeps its `updated_at`.

### How unit insights are calculated (`GET /insights/units`)

1. One row per **current** syllabus unit (from `syllabus.service.get_units`), Unit 1 first.
2. `mastery` = the student's **newest** `unit_mastery` snapshot for that unit (written by the
   diagnostic today; quizzes and exams later). `source` and `measured_at` say what measured it and when.
3. Grade and status come from the same bands as topic insights (`grading.py`). A unit never measured has
   `mastery: null`, status `not_attempted` and "Not assessed yet" - **never 0 %**.
4. `change_week` = newest mastery − the newest snapshot **older than 7 days**, for that same unit.
   A unit first measured this week has `change_week: null` (nothing to compare with).
5. `average_mastery`, `strongest` and `weakest` use assessed units only (ties: the lower unit number).
   Snapshots of units no longer in the syllabus are ignored.

### After an attempt is marked (`after_attempt_marked`)

Exams and quizzes call **one** function after marking, in the same transaction (the caller commits).
It replaces their current `refresh_topic_progress(...)` call:

```python
from shared.enums import MasterySource

await performance_service.after_attempt_marked(
    session, user.id, attempt.id, source=MasterySource.EXAM  # QUIZ / PRACTICE / DIAGNOSTIC
)
```

It runs, in order:

| Step | What it saves |
|---|---|
| `record_mistakes` | one `mistakes` row per wrong MCQ answer (details below) |
| `update_mastery` | a `unit_mastery` snapshot per unit in the attempt, and `concept_mastery` for every concept the attempt touched |
| `refresh_topic_progress` | `user_topic_progress` for the Learn screens |

- **Unit snapshots** use `grading.mastery_percent(correct, asked)` = (correct + 0.5) / (asked + 1), the
  diagnostic's formula, over this attempt only. Unanswered questions count as asked (wrong), like the
  diagnostic. For `source=DIAGNOSTIC` this step is skipped, because the diagnostic saves its own.
- **Concept mastery** is recomputed from **all** the student's answers to questions linked to the concept
  (`question_concepts`), with the same formula, stored 0-1. Nothing happens until questions are linked.
- Call it **once per attempt**: unit snapshots are history rows, so a second call would add another.
  Mistakes and concept mastery are safe to repeat.

### How concept insights are calculated (`GET /insights/concepts`)

Concepts are the syllabus sub-topics. A student's answer counts for a concept when its question is linked
to the concept in `question_concepts` (a question linked to two concepts counts for both). Scoring is
**the same rule as topics** (`score_level`): percent correct over valid answers, the grade bands, and
"reliable" only from 5 answers. Concepts are listed weakest first; `weak_concepts` are reliable S/F ones.

`linked_answers` / `total_answers` show how many of the student's answers had a concept link. **While no
questions are linked, the list is empty and the `note` says why** - it does not mean nothing is weak.

### How mistakes are recorded (`record_mistakes(session, user_id, attempt_id)`)

`after_attempt_marked` calls it. To call it on its own, do it **after the attempt is marked**, in the same
transaction; the caller commits:

```python
await performance_service.record_mistakes(session, user.id, attempt.id)
```

- One `mistakes` row per **wrong** MCQ answer. Unanswered and unreliable answers are not mistakes
  (the same rule as the topic scores).
- `mistake_type` is `misconception` when the chosen wrong option is linked to a misconception, otherwise
  `knowledge_gap`. Other types (such as `careless`) can't be told apart automatically.
- `concept_id` is the misconception's concept, otherwise the concept the question tests most, otherwise empty.
- Calling it twice for an attempt adds nothing. Wrong answers in a **later** attempt are new mistakes,
  even for the same question.

### Admin analytics (`/api/v1/admin/analytics`, role admin)

Routes live in `admin/analytics_admin.py`; the logic is the `analytics_*` functions in this module's
`service.py`. All three take `?days=` (1-365, default 30), a period ending today (Sri Lanka date).
They return totals over **all students**, never one student's data, and admins' own activity is left out.

| Endpoint | Returns |
|---|---|
| `GET /overview` | Total and new students, active students and the change from the previous period, finished attempts, MCQ answers, and active students per day (0 on quiet days, so charts have no gaps) |
| `GET /performance` | Average mastery per unit (each student's newest value; not limited to the period), the 10 most-missed topics, the 10 most chosen misconceptions |
| `GET /ai-usage` | Requests per feature and per day, images, cost and tokens |

- A topic needs at least 5 answers (`MIN_QUESTIONS_FOR_RELIABLE_RESULT`) to be listed as most-missed.
- Most-missed topics and misconceptions come from the **stored answers**, so they don't depend on
  `record_mistakes` being called.
- A unit nobody has been measured in has `average_mastery: null`, never 0 %.
- **Cost and tokens are `null`, not 0, until they are recorded.** `ai_service/daily_limits.py` only logs
  that a call happened (provider, model, operation, prompt, images): nothing writes `cost_usd`,
  `input_tokens`, `output_tokens`, `latency_ms` or `user_id` yet.
- Calls are only logged when that provider has a daily cap set, because logging lives in `use_quota`.
  With a cap of 0 (no limit) the requests are not counted.
- The Figma "Evaluation accuracy" panel is not here: it needs written-answer evaluation (later).

### How the summary is calculated (`GET /insights/summary`)

One number per Insights card, built from the **same functions** as the detail endpoints, so the
overview never disagrees with them:

| Field | Comes from |
|---|---|
| `overall_mastery`, `units_assessed`, `total_units`, `strongest_unit`, `weakest_unit` | `/insights/units` (`average_mastery`, ...) |
| `mastery_change_week` | average of each unit's own `change_week` (units without one are skipped; `null` if none) |
| `mcq`, `attempts_completed` | `/insights/topics` (`overall`, `attempts_analysed`) |
| `topics` | number of topics per status; `weak_topics` = reliable S/F topics, weakest first |
| `streak_days` | consecutive study days ending today, or yesterday if not studied yet today |
| `study_days_last_7`, `last_study_date` | `study_activity` (Sri Lanka date) |

A new student gets `null` and `0`, never made-up values.

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

## One mastery scale (proposal)

Three different scales are in use, so the same score can be "strong" on one screen and "ok" on another:

| Where | Owner | Scale |
|---|---|---|
| Topic / unit / concept insights, exam weak topics | Keshomigha | `grading.py`: A ≥ 75, B ≥ 65, C ≥ 55, S ≥ 35, F below (weak = S or F) |
| Diagnostic result (`quizzes/service.py`) | Udith | strong ≥ 70, ok ≥ 40 |
| Learn unit status (`syllabus/service.py`) | Samni | strong ≥ 75, improving ≥ 40 |

Proposal: everyone uses `grading.py`, which is meant to be the one place for thresholds:

- the formula: `grading.mastery_percent(correct, asked)`
- the level: `grading.grade_for(percent)` → `grade`, `label`, `status` (`strong` / `good` / `developing` /
  `weak` / `very_weak`), `understanding`
- weak or not: `grading.is_weak_percent(percent)`

To be agreed by Keshomigha, Udith and Samni; then the diagnostic and Learn switch to these functions.

## Which attempts count

One rule for the whole module (`FINISHED_ATTEMPT_STATUSES` in `repository.py`): topic insights, the
summary, mistakes, Learn progress and admin analytics all use it, so they never disagree.

| Attempt status | Counts? | Why |
|---|---|---|
| `submitted`, `graded` | ✅ | Marked (exams and the diagnostic write `graded`) |
| `evaluated` | ✅ | Marked by written-answer evaluation; its MCQ answers count like any other |
| `in_progress` | ❌ | Not marked yet |
| `abandoned` | ❌ | Never finished |

**Every attempt kind counts, the diagnostic included.** Its answers are real answers to approved
questions, and for a new student the only data there is. With 15 questions over 10 units a topic rarely
reaches the 5-answer minimum from the diagnostic alone, so it can't make a topic look weak on its own.

## How topic insights are calculated

1. Read the student's MCQ `responses` from **their own** finished attempts (see "Which attempts
   count" below). Another student's `attempt_id` → 403, unknown → 404.
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
Tests: `tests/api/test_performance.py`, `tests/api/test_mistakes.py`, `tests/api/test_analytics_admin.py`,
`tests/api/test_mastery_concepts.py`.
