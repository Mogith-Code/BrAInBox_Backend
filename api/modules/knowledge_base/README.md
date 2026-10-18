# `knowledge_base` module

| | |
|---|---|
| **Owner** | Keshomigha |
| **Purpose** | Model answers, answer points and keywords used to mark answers. |
| **Tables** | `model_answers`, `answer_points`, `keywords` |
| **Jira epic** | BRN-E11 Knowledge Base *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/knowledge_base` (tasks: `feature/knowledge_base/BRN-xx-short-name`) |

## Planned endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/knowledge-base/questions/{id}/model-answer` | Model answer (after an attempt) |
| - | (service) | get_marking_scheme(question_id) used by evaluation |

Placeholder right now: `GET /api/v1/knowledge-base/status` → `{"module": "knowledge_base", "status": "todo"}` (needs login).

## Files

| File | What goes in it |
|---|---|
| `router.py` | HTTP endpoints only (validate, check role, call service) |
| `schemas.py` | Pydantic request/response models |
| `service.py` | Business logic |
| `repository.py` | All SQL queries for this module |

Models live in `shared/db/models/`. Call other modules through their `service.py`, never their `repository.py`.
Tests: `tests/api/test_knowledge_base.py`.
