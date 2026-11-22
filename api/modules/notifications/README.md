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
| `community_reply` | community | `community.service.create_reply` (an approved reply to someone else's post) and `on_answer_suggested` (the AI answer). Skipped when the author turned **community replies** off (`PATCH /settings`) |
| `system` | other | moderation warnings (`community.service._warn`) |

**Study reminders** (`study_reminder`, type `reminder`) have no sender yet. Whoever adds one must read
`profiles.service.get_notification_settings(session, user_id)` and send only when `study_reminders` is true, at
`reminder_time` (24 h `"HH:mm"`, Sri Lanka time).

Other modules call `notifications.service.notify(session, user_id, type, title, body, data)`. It only adds the
row; the caller's commit saves it.

Tests: `tests/api/test_notifications.py`.

## Account delete / data export (called by the auth module)

Used by `DELETE /auth/me` and `GET /auth/me/export` (see `api/modules/auth/README.md`). Nothing is committed here; auth commits once for all modules.

`delete_user_data` deletes the student's notifications and push device tokens. `count_devices` gives the number shown in the export (never the FCM tokens).
