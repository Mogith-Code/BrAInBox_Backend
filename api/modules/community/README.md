# `community` module

| | |
|---|---|
| **Owner** | Mogith *(backend being built by Keshomigha, see `shared/db/models/community.py`; confirm and update)* |
| **Purpose** | Study groups, Q&A posts, replies (incl. AI suggested answers), votes, reports. |
| **Tables** | `community_groups`, `group_members`, `posts`, `replies`, `votes`, `content_reports` |
| **Jira epic** | BRN-E14 Community *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/community` (tasks: `feature/community/BRN-xx-short-name`) |

## Built: admin side (`admin/moderation_admin.py`)

| Function (`service.py`) | What it does |
|---|---|
| `moderation_queue` | open `content_reports` (posts, replies) + visual reports (visuals module), one item per target, oldest first |
| `resolve_report` | keep / warn / remove; closes every open report of the target; warn adds an in-app notification for the author. keep / warn show again a post / reply that was hidden (flagged) after 3 reports |
| `list_groups`, `create_group` | study groups with member count and moderator (409 `GROUP_NAME_TAKEN`) |

`posts.moderation_reason` / `moderation_score` (and the same on `replies`, migration `0006_moderation_flags`) are the
AI moderator's label and confidence (0-1); the MODERATE_POST job will fill them.
Tests: `tests/api/test_admin_moderation.py`.

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
| POST | `/api/v1/posts/{id}/replies` | ✅ done | Reply. Members of the post's group only → 403 `NOT_A_MEMBER` |
| PATCH | `/api/v1/replies/{id}` | ✅ done | Edit my reply. Not mine → 403 `NOT_REPLY_AUTHOR`. Unknown → 404 `REPLY_NOT_FOUND` |
| DELETE | `/api/v1/replies/{id}` | ✅ done | Delete my reply (or any reply as admin). Soft delete |
| POST | `/api/v1/posts/{id}/accept/{reply_id}` | ✅ done | The post's author marks the best answer (replaces the old one). Returns the post with replies |
| DELETE | `/api/v1/posts/{id}/accept` | ✅ done | The post's author un-marks it |
| POST | `/api/v1/votes` | ✅ done | `{post_id}` or `{reply_id}` + `value` 1 / -1 (0 removes my vote). Members only; not on my own → 403 `CANNOT_VOTE_OWN` |
| POST | `/api/v1/posts/{id}/report` | ✅ done | Report a post: `{reason, details?}`. Again while open → 409 `ALREADY_REPORTED`; my own → 400 `CANNOT_REPORT_OWN` |
| POST | `/api/v1/replies/{id}/report` | ✅ done | Report a reply (same rules) |

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
- **Settings > Data & privacy:** an author with `show_name_in_community: false` (`PATCH /privacy`) is shown as
  `"A/L student"` on their posts and replies, to every viewer including themselves
  (`profiles.service.users_hiding_name`).
- **Settings > Notifications:** the `community_reply` notification is only sent when the post's author has
  `community_replies: true` (`profiles.service.wants_community_replies`).

### Replies and the accepted answer

- Only **members** of the post's group reply; only the **author** edits; the author **or an admin** deletes
  (soft delete). Replies follow the same "who sees what" rule as posts.
- `reply_count` counts **visible** (approved) replies. It changes inside the database in the same transaction
  as the reply / delete, so replies at the same moment are all counted, and it never goes below 0.
- The **post's author** picks one accepted answer (`accepted_reply_id` on the post, `is_accepted` on the
  reply). Accepting another reply replaces it; `DELETE /posts/{id}/accept` removes it. Deleting the accepted
  reply removes the acceptance. A reply from another post → 404 `REPLY_NOT_FOUND`.

### Votes

- One vote per person per post or reply (`uq_votes_user_post` / `uq_votes_user_reply`). Voting again **changes**
  the vote and the score moves by the difference; `value: 0` removes it.
- Members only; never on your own post or reply.
- The post / reply row is **locked** while a vote is saved, so votes on it are handled one at a time: the
  score can't miscount (two students at once, or one student tapping twice).
- Posts and replies return `my_vote` (1, -1 or 0) so the app can highlight the arrow.

### Reports

- Anyone who can see a post or reply can report it, with a reason (`spam`, `offensive`, `wrong_info`,
  `off_topic`, `other`) and optional details. Saved in `content_reports` with status `pending` - the admin
  moderation queue reads it from there.
- One **open** report per person per post or reply; you can't report your own.
- **Safety net:** when `REPORTS_TO_HIDE` (3) different people have an open report on a post or reply, it is
  hidden (`flagged`) until an admin decides; a hidden reply stops counting in `reply_count`. Set it to 0 to
  turn this off. *(When an admin approves it again, `reply_count` must go back up - admin moderation, Mogith.)*

### Moderation (decision)

Every new post and reply is classified by the AI moderator (`POST /sync/moderate`) before it is saved:
`ok` -> `approved` (published); `off_topic` / `inappropriate` -> `flagged` (hidden from others until an admin
decides). **When the AI service can't be reached the content is held as `pending`** with
`moderation_reason = "Held: AI moderation was unavailable"`: only its author sees it, and a held reply does not
count in `reply_count`. Our users are minors, so nothing unchecked is published (`NEW_CONTENT_STATUS` in
`service.py`). Students can still report approved content (`content_reports`, the admin moderation queue).
Edits don't change the status.

Open: held content is not yet re-checked or shown in the admin queue, so it stays pending until someone
releases it.

## Account delete / data export (called by the auth module)

Used by `DELETE /auth/me` and `GET /auth/me/export` (see `api/modules/auth/README.md`). Nothing is committed here; auth commits once for all modules.

`delete_user_data` hard-deletes the student's posts (with the replies under them), replies, votes, reports and group memberships, takes their votes off other posts' scores and their replies off other posts' reply counts / accepted answer, and returns the post image paths. `export_user_data` gives `{posts, replies}`.

## Files

| File | What goes in it |
|---|---|
| `router.py` | HTTP endpoints only (validate, check role, call service) |
| `schemas.py` | Pydantic request/response models |
| `service.py` | Business logic |
| `repository.py` | All SQL queries for this module |

Models live in `shared/db/models/`. Call other modules through their `service.py`, never their `repository.py`.
Tests: `tests/api/test_community.py`.
