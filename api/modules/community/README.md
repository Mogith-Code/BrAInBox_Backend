# `community` module

| | |
|---|---|
| **Owner** | Mogith *(backend being built by Keshomigha, see `shared/db/models/community.py`; confirm and update)* |
| **Purpose** | Study groups, Q&A posts, replies (incl. AI suggested answers), votes, reports. |
| **Tables** | `community_groups`, `group_members`, `posts`, `replies`, `votes`, `content_reports` |
| **Jira epic** | BRN-E14 Community *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/community` (tasks: `feature/community/BRN-xx-short-name`) |

## Endpoints

All need a logged-in user. Paths follow the app's plan (`apps/mobile/lib/features/community/README.md`):
posts live under their group (`/groups/{id}/posts`).

| Method | Path | Status | Description |
|---|---|---|---|
| GET | `/api/v1/groups` | ✅ done | Groups I can see: General first, then one per unit. Private groups only when I'm a member |
| GET | `/api/v1/groups/{id}` | ✅ done | One group. `id` = UUID or slug (`general`, `unit-6`). Unknown → 404 `GROUP_NOT_FOUND` |
| POST | `/api/v1/groups/{id}/join` | ✅ done | Join. Joining again changes nothing |
| DELETE | `/api/v1/groups/{id}/join` | ✅ done | Leave. Leaving again changes nothing |
| GET | `/api/v1/groups/{id}/posts` | ✅ done | Feed of a group: `?sort=new` (default) or `top`, paged (`page`, `size`) |
| POST | `/api/v1/groups/{id}/posts` | ✅ done | Create a post. Members only → 403 `NOT_A_MEMBER`. Topic must be in the group's unit → 400 `TOPIC_NOT_IN_GROUP_UNIT` |
| GET | `/api/v1/posts/{id}` | ✅ done | Post with its replies (accepted answer first, then highest score). Not visible → 404 `POST_NOT_FOUND` |
| PATCH | `/api/v1/posts/{id}` | ✅ done | Edit my post (send only the fields to change). Not mine → 403 `NOT_POST_AUTHOR` |
| DELETE | `/api/v1/posts/{id}` | ✅ done | Delete my post (or any post as admin). Soft delete |
| POST | `/api/v1/posts/{id}/replies` | planned | Reply |
| POST | `/api/v1/posts/{id}/accept/{reply_id}` | planned | The post's author marks the best answer |
| POST | `/api/v1/votes` | planned | +1 / -1 on a post or reply |
| POST | `/api/v1/posts/{id}/report` | planned | Report a post (and `/replies/{id}/report` for a reply) |

Placeholder: `GET /api/v1/community/status` → `{"module": "community", "status": "todo"}` (needs login).

### Groups

- The groups come from `scripts/seed_dev.py`: a default **General** group plus one per unit (`unit-1` ... `unit-10`).
- A **private** group is invisible to non-members: listing hides it and `GET` / join / leave answer 404, so its
  existence isn't leaked. It can't be joined from the app.
- `member_count` is changed inside the database in the same transaction as the join / leave, so two taps at
  the same moment can't miscount, and it never goes below 0.

### Posts

- **Who can do what:** anyone who can see a group reads its posts; only **members** post; only the **author**
  edits; the author **or an admin** deletes.
- **Who sees what:** approved posts, plus **my own** posts that are `pending` or `flagged` (with that status, so the
  app can show "under review"). `removed` and deleted posts are hidden from everyone. Replies follow the same rule.
- A post's `unit_id` is its group's unit (or its topic's unit). Its `topic_id` must belong to the group's unit.
- **Tags:** at most 5, each up to 50 characters, stored trimmed and lower-case without duplicates.
- **Delete is soft** (`deleted_at`): the row stays so replies and votes keep working, but nobody sees it.
- Authors are shown by display name only (`"Student"` when they have none); `author` is `null` for an AI suggested
  answer or a deleted account.

### Moderation (decision)

**For now, new posts are published straight away** (`moderation_status = approved`) and students can report
bad ones; reports go to `content_reports`, the admin moderation queue. This is one setting,
`NEW_POST_STATUS` in `service.py`, so it can be switched later. Edits don't change the status.

Later (AI step): a new post starts as `pending`, the `MODERATE_POST` job checks it (bullying, hate, sexual
content, personal data, spam, cheating), then marks it `approved` or `flagged`. Flagged posts are hidden from
others until an admin decides. If the AI is unavailable the post stays `pending` and is retried.

## Files

| File | What goes in it |
|---|---|
| `router.py` | HTTP endpoints only (validate, check role, call service) |
| `schemas.py` | Pydantic request/response models |
| `service.py` | Business logic |
| `repository.py` | All SQL queries for this module |

Models live in `shared/db/models/`. Call other modules through their `service.py`, never their `repository.py`.
Tests: `tests/api/test_community.py`.
