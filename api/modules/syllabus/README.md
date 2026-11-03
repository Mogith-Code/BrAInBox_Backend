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

## Admin: syllabus manager (`/api/v1/admin/syllabus`, role admin)

Routes live in `admin/syllabus_admin.py`; the logic is the `admin_*` functions in this module's
`service.py`. Admins see **everything**, outdated rows included. Edits are partial (PATCH: send only
the fields to change); required fields (`number`, `title`, `name`) can't be cleared → 400 `FIELD_REQUIRED`.

| Method | Path | Notes |
|---|---|---|
| GET | `/admin/syllabus/units` | All units with `topic_count` |
| POST | `/admin/syllabus/units` | 201. Number taken → 409 `UNIT_NUMBER_TAKEN` |
| PATCH | `/admin/syllabus/units/{id}` | Edit, or `is_outdated: true` |
| GET | `/admin/syllabus/units/{id}/topics` | All topics with `concept_count` |
| POST | `/admin/syllabus/units/{id}/topics` | 201. Number taken in this unit → 409 `TOPIC_NUMBER_TAKEN` |
| PATCH | `/admin/syllabus/topics/{id}` | Edit, or `is_outdated: true` |
| DELETE | `/admin/syllabus/topics/{id}` | 204 |
| GET | `/admin/syllabus/topics/{id}/concepts` | All concepts |
| POST | `/admin/syllabus/topics/{id}/concepts` | 201. Code taken → 409 `CONCEPT_CODE_TAKEN` |
| PATCH | `/admin/syllabus/concepts/{id}` | Edit, or `is_outdated: true` |
| DELETE | `/admin/syllabus/concepts/{id}` | 204 |

**Delete rules.** Anything students have used should be **marked outdated**, not deleted:
- **Units are never deleted.** Deleting one would also delete students' unit-mastery history.
- A **topic** can be deleted only when it has no concepts (409 `TOPIC_HAS_CONCEPTS`) and no question,
  note or visual points at it (409 `IN_USE`).
- A **concept** can be deleted only when no question, note, visual or misconception points at it
  (409 `IN_USE`). Its students' `concept_mastery` rows are removed with it.

**Embeddings.** Changing a concept's `name`, `description` or `learning_outcome` clears its stored
embedding (it no longer matches the text); the next embedding run recomputes it.

**Audit log.** Not written yet: `admin.service.record_audit` is still a TODO (Mogith).

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
