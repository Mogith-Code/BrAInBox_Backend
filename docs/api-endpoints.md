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

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/auth/register` | Create the users row for a new Firebase account (uses FirebaseClaimsDep, not CurrentUserDep) |
| GET | `/api/v1/auth/me` | Current user |
| PATCH | `/api/v1/auth/me` | Update display name etc. |
| DELETE | `/api/v1/auth/me` | Delete / anonymise the account |

## profiles — Mogith

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/profile` | My profile |
| PATCH | `/api/v1/profile` | Update my profile |

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
| POST | `/api/v1/uploads` | Upload a file -> creates SUMMARIZE_UPLOAD job |
| GET | `/api/v1/uploads/{id}` | Upload status + summary |
| GET | `/api/v1/library` | My saved items |
| POST | `/api/v1/library` | Save an item |
| DELETE | `/api/v1/library/{id}` | Remove an item |

## visuals — Mogith

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/topics/{id}/visuals` | Approved visuals for a topic |
| POST | `/api/v1/visuals/generate` | Request a visual -> GENERATE_VISUAL job |
| POST | `/api/v1/visuals/{id}/report` | Report a wrong visual |

## questions — Udith

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/questions/{id}` | One question with options (no answer key) |
| GET | `/api/v1/topics/{id}/questions` | Practice questions for a topic |
| POST | `/api/v1/questions/{id}/explain` | Explain an MCQ answer (sync AI call) |

## quizzes — Udith

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/quizzes` | Start a quiz for a topic/unit |
| GET | `/api/v1/quizzes/{id}` | Quiz with questions |
| POST | `/api/v1/quizzes/{id}/responses` | Submit answers |
| GET | `/api/v1/quizzes/{id}/results` | Score + explanations |
| POST | `/api/v1/quizzes/diagnostic` | Start the diagnostic test |

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
| GET | `/api/v1/jobs/{id}` | Job status + result (only the requester or an admin) |

## admin (`/api/v1/admin`, role admin)

| File | Owner | Prefix | Planned endpoints |
|---|---|---|---|
| `content_admin.py` | Samni | `/admin/content` | notes CRUD, approve/reject, trigger note generation |
| `rag_admin.py` | Samni | `/admin/rag` | `POST /documents` (upload + RAG_INGEST job), `GET /documents`, `POST /documents/{id}/reindex` |
| `questions_admin.py` | Udith | `/admin/questions` | question bank, MCQ → misconception mapping, quality review queue, past papers |
| `knowledge_admin.py` | Keshomigha | `/admin/knowledge` | model answers, answer points, keywords |
| `syllabus_admin.py` | Keshomigha | `/admin/syllabus` | units / topics / concepts CRUD |
| `analytics_admin.py` | Keshomigha | `/admin/analytics` | usage, performance, AI cost |
| `moderation_admin.py` | Mogith | `/admin/moderation` | reports queue (posts, replies, visuals) |
| `users_admin.py` | Mogith | `/admin/users` | list users, change role, disable |

## Internal AI service (`ai_service`, port 8001, not public)

Every request needs `X-Service-Token`. Only `api/core/ai_client.py` calls these.

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Status + which providers are active (fake or real) |
| POST | `/jobs/run` | Run one AI job: `{job_id, job_type, payload}` → `{result}` |
| POST | `/sync/explain-mcq` | ✅ Explain wrong MCQ answers: `{items: [...]}` → `{explanations: {question_id: text}}` |
| POST | `/sync/tag-post` | Suggest tags for a community post (fast) |
| POST | `/sync/keyword-score` | Quick keyword score for an answer (fast) |
