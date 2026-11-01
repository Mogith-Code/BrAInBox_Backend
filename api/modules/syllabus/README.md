# `syllabus` module

| | |
|---|---|
| **Owner** | Keshomigha |
| **Purpose** | Read-only syllabus tree for students: units -> topics -> concepts. |
| **Tables** | `units`, `topics`, `concepts` |
| **Jira epic** | BRN-E03 Syllabus *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/syllabus` (tasks: `feature/syllabus/BRN-xx-short-name`) |

## Endpoints

All need a logged-in user.

| Method | Path | Status | Description |
|---|---|---|---|
| GET | `/api/v1/units` | ✅ done | Current units, Unit 1 first, each with `topic_count` |
| GET | `/api/v1/units/{id}/topics` | ✅ done | The unit and its current topics (syllabus order), each with `concept_count`. Unknown or outdated unit → 404 `UNIT_NOT_FOUND` |
| GET | `/api/v1/topics/{id}` | ✅ done | One topic with its unit and current concepts. Unknown → 404 `TOPIC_NOT_FOUND` |

Placeholder: `GET /api/v1/syllabus/status` → `{"module": "syllabus", "status": "todo"}` (needs login).

### Current vs outdated

Lists show the **current** syllabus only: units, topics and concepts with `is_outdated = true` are hidden
and not counted. `GET /topics/{id}` still opens an outdated topic (old notes and questions link to it) and
returns `is_outdated: true`, so the app can show an "Outdated syllabus" tag.

### For other modules (`service.py`)

| Function | Used by |
|---|---|
| `get_topics(topic_ids)` | exams, content: check topic ids, get titles + unit |
| `list_units()` | quizzes, home: units with `exam_weight` |
| `list_topics_by_unit(unit_ids)` | home: current topics per unit |

## Files

| File | What goes in it |
|---|---|
| `router.py` | HTTP endpoints only (validate, check role, call service) |
| `schemas.py` | Pydantic request/response models |
| `service.py` | Business logic |
| `repository.py` | All SQL queries for this module |

Models live in `shared/db/models/`. Call other modules through their `service.py`, never their `repository.py`.
Tests: `tests/api/test_syllabus.py`.
