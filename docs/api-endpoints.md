# Planned API endpoints

All routes are under `/api/v1` and need `Authorization: Bearer <Firebase ID token>`, except `GET /api/v1/health`.
Admin routes are under `/api/v1/admin` and need role `admin`.
Every module currently has one placeholder: `GET /api/v1/<module>/status`. Admin areas have `GET /api/v1/admin/<area>/status`.
The live list is always at `http://localhost:8000/docs`.

Errors always look like `{"error": {"code": "SOME_CODE", "message": "..."}}`.

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/health` | API + database health (no login) |

## auth — Mogith

"token" = Firebase ID token. 6-digit codes: 10 min, 5 wrong tries, 60 s resend cooldown.

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/v1/auth/register` | token | ✅ Create / update my users row `{full_name, phone?, consent}` → `UserOut` (201 new, 200 existing) |
| GET | `/api/v1/auth/me` | token | ✅ My account + onboarding flags (`USER_NOT_FOUND` before register) |
| PATCH | `/api/v1/auth/me` | token | ✅ Change `full_name` / `phone` |
| DELETE | `/api/v1/auth/me` | token | ✅ Delete account (DB + Firebase) → 204 |
| POST | `/api/v1/auth/email-code/send` | token | ✅ Email a verification code (`ALREADY_VERIFIED`, `RESEND_TOO_SOON` 429) |
| POST | `/api/v1/auth/email-code/verify` | token | ✅ `{code}` → `UserOut` with `email_verified: true` |
| POST | `/api/v1/auth/password-reset/send` | none | ✅ `{email}` → always `{sent: true, ...}` |
| POST | `/api/v1/auth/password-reset/verify` | none | ✅ `{email, code}` → `{reset_token, expires_in}` |
| POST | `/api/v1/auth/password-reset/complete` | none | ✅ `{reset_token, new_password}` → `{reset: true}` |

## profiles — Mogith

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/profile/options` | ✅ Choices for setup: streams, subjects (Biology only available), exam years, grades, study times |
| GET | `/api/v1/profile` | ✅ My profile (`ProfileOut`, includes `weekly_hours`) |
| PATCH | `/api/v1/profile` | ✅ Save any subset of the setup fields |
| POST | `/api/v1/profile/complete` | ✅ Finish setup (`PROFILE_INCOMPLETE` + `missing`) |

## home — Samni

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/home/summary` | ✅ Greeting, streak, days to A/L, next best action (AI reason), today's plan, mastery + weekly change, continue learning |
| PATCH | `/api/v1/home/plan/{item_id}` | ✅ `{done}` → updated plan item |

## syllabus — Keshomigha

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/units` | All 10 units |
| GET | `/api/v1/units/{id}/topics` | Topics of a unit |
| GET | `/api/v1/topics/{id}` | One topic with its concepts |

## content — Samni

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/topics/{id}/notes` | Approved notes for a topic (full + short) |
| POST | `/api/v1/uploads/text` | Text notes -> SUMMARIZE_UPLOAD job (202, poll GET) |
| POST | `/api/v1/uploads/pdf` | PDF upload (multipart) -> storage + SUMMARIZE_UPLOAD job (202, poll GET) |
| GET | `/api/v1/uploads/{id}` | Upload status + summary |
| GET | `/api/v1/library` | My saved items |
| POST | `/api/v1/library` | Save an item |
| DELETE | `/api/v1/library/{id}` | Remove an item |

## visuals — Mogith

Details, visibility rules and how visuals are made: [`api/modules/visuals/README.md`](../api/modules/visuals/README.md).

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/topics/{topic_id}/visuals` | ✅ `{topic_id, topic_title, unit_code, unit_title, visuals: [VisualOut]}`: approved + my own (not rejected/archived), newest first |
| GET | `/api/v1/visuals/{visual_id}` | ✅ One `VisualOut` (`VISUAL_NOT_FOUND` if not approved and not mine) |
| POST | `/api/v1/visuals/generate` | ✅ `{prompt (5-300), visual_type, style, topic_id?}` → 202 `{job_id}` (GENERATE_VISUAL); 20 per day (`VISUAL_LIMIT_REACHED` 429) |
| POST | `/api/v1/visuals/{visual_id}/report` | ✅ `{reason, details? (≤500)}` → 201 (`ALREADY_REPORTED` 409 while my report is pending) |

`VisualOut`: `id, title, topic_id, concept_id, kind, image_url, mermaid_code, alt_text, labels [{number, name, description, x, y}],
style, width, height, is_ai_generated, is_verified, created_at`. `image_url` loads without a login header
(Firebase signed URL, or `/api/v1/files/visuals/...` in dev without a bucket).

## questions — Udith

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/questions/{id}` | One question with options (no answer key) |
| GET | `/api/v1/topics/{id}/questions` | Practice questions for a topic |
| POST | `/api/v1/questions/{id}/explain` | Explain an MCQ answer (sync AI call) |

## quizzes — Udith

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/diagnostic/start` | ✅ 15 MCQs over 10 units (resumes the unfinished test) |
| POST | `/api/v1/diagnostic/{attempt_id}/answer` | ✅ Save one answer `{question_id, option_id}` |
| POST | `/api/v1/diagnostic/{attempt_id}/submit` | ✅ Mastery per unit, strongest / needs work, AI summary |
| POST | `/api/v1/diagnostic/skip` | ✅ Skip for now |
| GET | `/api/v1/diagnostic/result` | ✅ Latest diagnostic result |
| POST | `/api/v1/quizzes` | Start a quiz for a topic/unit |
| GET | `/api/v1/quizzes/{id}` | Quiz with questions |
| POST | `/api/v1/quizzes/{id}/responses` | Submit answers |
| GET | `/api/v1/quizzes/{id}/results` | Score + explanations |

## exams — Udith

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/papers/generate` | ✅ AI model paper for 1–10 topics (BUILD_PAPER) |
| POST | `/api/v1/papers/{id}/submit` | ✅ Mark answers, topic scores, weak topics, explanations |
| GET | `/api/v1/papers` | List papers |
| GET | `/api/v1/papers/{id}` | One paper |
| POST | `/api/v1/attempts` | Start an attempt |
| GET | `/api/v1/attempts/{id}` | Attempt with answers |

## quality — Udith

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/questions/{id}/report` | Report a wrong question |
| - | (service) | Review-queue logic used by admin/questions_admin.py |

## evaluation — Keshomigha

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/evaluations` | Evaluate a typed answer -> EVALUATE_ANSWER job |
| POST | `/api/v1/evaluations/ocr` | Upload a handwritten answer photo -> OCR_ANSWER job |
| GET | `/api/v1/evaluations/{id}` | Result: estimated marks, matched points, feedback |

## knowledge_base — Keshomigha

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/knowledge-base/questions/{id}/model-answer` | Model answer (after an attempt) |
| - | (service) | get_marking_scheme(question_id) used by evaluation |

## performance — Keshomigha

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/insights/topics` | ✅ My topic-wise MCQ scores, grades, weak topics and feedback (`?attempt_id=` for one attempt) |
| GET | `/api/v1/insights/summary` | Overall progress |
| GET | `/api/v1/insights/units` | Mastery per unit |
| GET | `/api/v1/insights/concepts` | Weakest concepts |
| GET | `/api/v1/mistakes` | My mistakes (filter by type/unit) |
| - | (service) | record_mistake() and update_mastery() called by quizzes/exams/evaluation |

## recommendations — Udith

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/recommendations` | My recommendations |
| POST | `/api/v1/recommendations/{id}/dismiss` | Hide one |
| GET | `/api/v1/study-plan` | My active study plan |
| POST | `/api/v1/study-plan` | Create / regenerate a plan |
| PATCH | `/api/v1/study-plan/items/{id}` | Mark an item done |

## community — Mogith

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

## jobs — shared

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/jobs/{job_id}` | ✅ `{id, job_type, status, progress, result, error, error_code, created_at, finished_at}`; only the requester or an admin (`JOB_NOT_FOUND` otherwise). `error` is a sentence for the student |

## admin (`/api/v1/admin`, role admin)

| File | Owner | Prefix | Planned endpoints |
|---|---|---|---|
| `content_admin.py` | Samni | `/admin/content` | notes CRUD, approve/reject, trigger note generation |
| `rag_admin.py` | Samni | `/admin/rag` | `POST /documents` (upload + RAG_INGEST job), `GET /documents`, `POST /documents/{id}/reindex` |
| `questions_admin.py` | Udith | `/admin/questions` | question bank, MCQ → misconception mapping, quality review queue, past papers |
| `knowledge_admin.py` | Keshomigha | `/admin/knowledge` | model answers, answer points, keywords |
| `syllabus_admin.py` | Keshomigha | `/admin/syllabus` | units / topics / concepts CRUD |
| `analytics_admin.py` | Keshomigha | `/admin/analytics` | usage, performance, AI cost |
| `moderation_admin.py` | Mogith | `/admin/moderation` | ✅ `GET /reports` (visual reports with `visual_title` + `image_url`); planned: posts, replies, resolve |
| `users_admin.py` | Mogith | `/admin/users` | list users, change role, disable |

## Error codes (for the app's `ErrorMessages`)

Every error is `{"error": {"code": "...", "message": "..."}}`; some add fields (e.g. `retry_after`).
Failed AI jobs return `status: "failed"` with `error` (a sentence) and `error_code` from `GET /jobs/{job_id}`.

| Code | HTTP | Module | Meaning |
|---|---|---|---|
| `TOPIC_NOT_FOUND` | 404 | syllabus, content, visuals | unknown topic id |
| `VISUAL_NOT_FOUND` | 404 | visuals | unknown visual, or another student's visual that is not approved |
| `ALREADY_REPORTED` | 409 | visuals | my report of this visual is still pending |
| `VISUAL_LIMIT_REACHED` | 429 | visuals | daily visual limit reached; `retry_after` (seconds) + `Retry-After` header |
| `JOB_NOT_FOUND` | 404 | jobs | unknown job, or another student's job |
| `NOT_BIOLOGY` | job `error_code` | visuals | "I can only draw Biology visuals." |
| `AI_SERVICE_UNAVAILABLE` | 503 / job `error_code` | all AI features | the AI is busy or down; try again later |
| `FILE_NOT_FOUND` | 404 | visuals (dev file route) | no such stored image |

## Internal AI service (`ai_service`, port 8001, not public)

Every request needs `X-Service-Token`. Only `api/core/ai_client.py` calls these.

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Status + which providers are active (fake or real) |
| POST | `/jobs/run` | Run one AI job: `{job_id, job_type, payload}` → `{result}` |
| POST | `/sync/explain-mcq` | ✅ Explain wrong MCQ answers: `{items: [...]}` → `{explanations: {question_id: text}}` |
| POST | `/sync/tag-post` | Suggest tags for a community post (fast) |
| POST | `/sync/diagnostic-summary` | ✅ 2-sentence diagnostic summary (prompt `diagnostic/summary.v1`) |
| POST | `/sync/next-action` | ✅ One-sentence reason for the home "next best action" (prompt `home/next_action.v1`) |
| POST | `/sync/keyword-score` | Quick keyword score for an answer (fast) |
