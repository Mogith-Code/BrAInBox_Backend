# Notifications (backend)

| | |
|---|---|
| **Owner** | Mogith |
| **App screen** | Notification center, `apps/mobile/lib/features/notifications` (Figma F4) |
| **Table** | `notifications` (`shared/db/models/user.py`) |

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/notifications?limit=50&unread_only=false` | `{items, unread_count}`, newest first |
| `PATCH` | `/api/v1/notifications/{id}` | `{read: true}` (or `false` = unread again). 404 `NOTIFICATION_NOT_FOUND` |
| `POST` | `/api/v1/notifications/read-all` | `{updated: n}` |

Each item: `{id, type, event, title, body, created_at, read, ai_generated, data}`. `type` is the app's
`NotificationKind` (`reminder | recommendation | community | achievement | streak | other`; it picks the icon
and the filter chip). `event` is the backend `NotificationType`. `data` says where a tap goes.

## What creates notifications

| Event | `type` | Where |
|---|---|---|
| `job_done` | recommendation | `service.on_job_finished`, a listener in `api/core/jobs.py` (`register_job_listener`). Only the student background jobs in `JOB_MESSAGES` (summaries, notes, visuals, answer marking), on success and on failure |
| `plan_ready` | reminder | `recommendations.service.regenerate_plan` (a new weekly plan) |
| `community_reply` | community | `community.service.create_reply` (an approved reply to someone else's post) and `on_answer_suggested` (the AI answer) |
| `system` | other | moderation warnings (`community.service._warn`) |

Other modules call `notifications.service.notify(session, user_id, type, title, body, data)`. It only adds the
row; the caller's commit saves it.

Tests: `tests/api/test_notifications.py`.
