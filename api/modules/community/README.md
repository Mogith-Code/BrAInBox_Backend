# `community` module

| | |
|---|---|
| **Owner** | Mogith |
| **Purpose** | Study groups, Q&A posts, replies (incl. AI suggested answers), votes, reports. |
| **Tables** | `community_groups`, `group_members`, `posts`, `replies`, `votes`, `content_reports` |
| **Jira epic** | BRN-E14 Community *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/community` (tasks: `feature/community/BRN-xx-short-name`) |

## Built: admin side (`admin/moderation_admin.py`)

| Function (`service.py`) | What it does |
|---|---|
| `moderation_queue` | open `content_reports` (posts, replies) + visual reports (visuals module), one item per target, oldest first |
| `resolve_report` | keep / warn / remove; closes every open report of the target; warn adds an in-app notification for the author |
| `list_groups`, `create_group` | study groups with member count and moderator (409 `GROUP_NAME_TAKEN`) |

`posts.moderation_reason` / `moderation_score` (and the same on `replies`, migration `0006_moderation_flags`) are the
AI moderator's label and confidence (0-1); the MODERATE_POST job will fill them.
Tests: `tests/api/test_admin_moderation.py`.

## Planned endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/groups` | List groups |
| POST | `/api/v1/groups` | Create a group |
| POST | `/api/v1/groups/{id}/join` | Join a group |
| GET | `/api/v1/posts` | Feed (filter by group/topic/tag) |
| POST | `/api/v1/posts` | Create a post -> MODERATE_POST + SUGGEST_ANSWER jobs |
| GET | `/api/v1/posts/{id}` | Post with replies |
| POST | `/api/v1/posts/{id}/replies` | Reply |
| POST | `/api/v1/votes` | Up/down vote a post or reply |
| POST | `/api/v1/reports` | Report a post or reply |

Placeholder right now: `GET /api/v1/community/status` → `{"module": "community", "status": "todo"}` (needs login).

## Files

| File | What goes in it |
|---|---|
| `router.py` | HTTP endpoints only (validate, check role, call service) |
| `schemas.py` | Pydantic request/response models |
| `service.py` | Business logic |
| `repository.py` | All SQL queries for this module |

Models live in `shared/db/models/`. Call other modules through their `service.py`, never their `repository.py`.
Tests: `tests/api/test_community.py`.
