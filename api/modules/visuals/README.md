# `visuals` module

| | |
|---|---|
| **Owner** | Mogith |
| **Purpose** | Diagrams and illustrations for topics, AI generation and student reports. |
| **Tables** | `visuals`, `visual_reports` |
| **Jira epic** | BRN-E05 Visual Learning *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/visuals` (tasks: `feature/visuals/BRN-xx-short-name`) |

## Planned endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/topics/{id}/visuals` | Approved visuals for a topic |
| POST | `/api/v1/visuals/generate` | Request a visual -> GENERATE_VISUAL job |
| POST | `/api/v1/visuals/{id}/report` | Report a wrong visual |

Placeholder right now: `GET /api/v1/visuals/status` → `{"module": "visuals", "status": "todo"}` (needs login).

## Files

| File | What goes in it |
|---|---|
| `router.py` | HTTP endpoints only (validate, check role, call service) |
| `schemas.py` | Pydantic request/response models |
| `service.py` | Business logic |
| `repository.py` | All SQL queries for this module |

Models live in `shared/db/models/`. Call other modules through their `service.py`, never their `repository.py`.
Tests: `tests/api/test_visuals.py`.
