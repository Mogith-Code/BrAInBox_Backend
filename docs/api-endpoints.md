# Planned API endpoints

All routes are under `/api/v1` and need `Authorization: Bearer <Firebase ID token>`, except `GET /api/v1/health`.
Admin routes are under `/api/v1/admin` and need role `admin`.
Modules not built yet have a placeholder: `GET /api/v1/<module>/status`. Admin areas not built yet have `GET /api/v1/admin/<area>/status`.
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
| GET | `/api/v1/units` | ✅ Current units, Unit 1 first, with `topic_count` |
| GET | `/api/v1/subjects/{subject_id}/units` | ✅ Units of a subject + my progress (Learn) |
| GET | `/api/v1/units/{unit_id}/topics` | ✅ Topics of a unit + sub-topics + my progress (Learn) |
| GET | `/api/v1/topics/{topic_id}` | ✅ One topic with its sub-topics + my progress (Learn) |
| POST | `/api/v1/topics/{topic_id}/start` | ✅ Mark a topic as started (Learn, handled by the performance module) |

### Learn navigation (subject → units → topics → sub-topics)

Data comes from `data/syllabus/al_biology_syllabus.json` (`python scripts/seed_syllabus.py`).
Responses are **camelCase**. Ids in the path can be the public code or the UUID:

| Level | `id` (public code) | Stored in |
|---|---|---|
| subject | `biology` | `subjects.code` |
| unit | `u6` | `units.code` |
| topic | `bio-6.1` | `topics.code` |
| sub-topic | `bio-6.1.1` | `concepts.code` |

`uuid` is the database id. Use it wherever another endpoint asks for a `topic_id`, e.g.
`POST /uploads/text` or `POST /papers/generate`.

Progress comes from `user_topic_progress` for the logged-in student. A topic with no row is
`not_started`, `progressPct` 0, `isWeak` false.

- Topic `status`: `not_started` | `in_progress` | `mastered`. `progressPct` = the topic score (0–100).
- Unit `progressPct` = average topic score in the unit (not-started topics count as 0).
- Unit `status`: **`not_started`** when no topic of the unit has any activity. Otherwise, from
  `progressPct`: `strong` (≥ 75) | `improving` (40–74) | `weak` (< 40).

How progress changes:

| Event | Effect on the topic |
|---|---|
| `POST /topics/{topic_id}/start` | `not_started` → `in_progress`, score 0. Never changes an existing score or `mastered` |
| `POST /papers/{id}/submit`, `POST /diagnostic/{attempt_id}/submit` | Recomputed from all my finished attempts, the same score as `GET /insights/topics` |

| Topic result | `status` | `progressPct` | `isWeak` |
|---|---|---|---|
| No valid answers | unchanged | unchanged | unchanged |
| Fewer than 5 valid answers | `in_progress` | percent correct | `false` |
| 5+ valid answers, 75 % or more | `mastered` | percent correct | `false` |
| 5+ valid answers, 55–74 % | `in_progress` | percent correct | `false` |
| 5+ valid answers, below 55 % | `in_progress` | percent correct | `true` |

Questions with no topic (papers from `POST /papers/generate-by-units`) don't change topic progress.

**`GET /api/v1/subjects/biology/units`** → 200

```json
[
  {
    "id": "u6",
    "uuid": "08bd699e-c905-46b8-817e-44e73bde406a",
    "number": 6,
    "title": "Genetics",
    "periods": 22,
    "icon": "dna",
    "topicCount": 5,
    "progressPct": 48,
    "status": "improving"
  },
  {
    "id": "u7",
    "uuid": "2f6c1a50-7f0e-4a55-9a53-6f0b5c1d9e12",
    "number": 7,
    "title": "Evolution",
    "periods": 10,
    "icon": "tree",
    "topicCount": 4,
    "progressPct": 0,
    "status": "not_started"
  }
]
```

**`POST /api/v1/topics/bio-6.1/start`** → 200 (no body). Safe to call every time the topic is opened.

```json
{
  "id": "bio-6.1",
  "uuid": "d1cf1dbb-eea9-4242-975d-b56e15e8a5c2",
  "status": "in_progress",
  "progressPct": 0,
  "isWeak": false
}
```

**`GET /api/v1/units/u6/topics`** → 200 (`topics` shortened to one item)

```json
{
  "unit": {
    "id": "u6",
    "uuid": "08bd699e-c905-46b8-817e-44e73bde406a",
    "number": 6,
    "title": "Genetics",
    "periods": 22,
    "icon": "dna",
    "topicCount": 5,
    "progressPct": 48,
    "status": "improving"
  },
  "summary": {"mastered": 1, "weak": 2},
  "topics": [
    {
      "id": "bio-6.1",
      "uuid": "d1cf1dbb-eea9-4242-975d-b56e15e8a5c2",
      "code": "6.1",
      "title": "Mendelian inheritance",
      "order": 1,
      "status": "mastered",
      "progressPct": 90,
      "isWeak": false,
      "subtopics": [
        {"id": "bio-6.1.1", "title": "Law of segregation"},
        {"id": "bio-6.1.2", "title": "Law of independent assortment"},
        {"id": "bio-6.1.3", "title": "Monohybrid cross"},
        {"id": "bio-6.1.4", "title": "Dihybrid cross"},
        {"id": "bio-6.1.5", "title": "Test cross"}
      ]
    }
  ]
}
```

**`GET /api/v1/topics/bio-6.1`** → 200

```json
{
  "id": "bio-6.1",
  "uuid": "d1cf1dbb-eea9-4242-975d-b56e15e8a5c2",
  "code": "6.1",
  "title": "Mendelian inheritance",
  "order": 1,
  "status": "mastered",
  "progressPct": 90,
  "isWeak": false,
  "subtopics": [
    {"id": "bio-6.1.1", "title": "Law of segregation"},
    {"id": "bio-6.1.2", "title": "Law of independent assortment"},
    {"id": "bio-6.1.3", "title": "Monohybrid cross"},
    {"id": "bio-6.1.4", "title": "Dihybrid cross"},
    {"id": "bio-6.1.5", "title": "Test cross"}
  ],
  "unitId": "u6",
  "unitNumber": 6,
  "unitTitle": "Genetics",
  "isOutdated": false
}
```

Lists show the current syllabus only (`is_outdated` rows are hidden, and an outdated unit is a
404). `GET /topics/{id}` still opens an outdated topic, with `isOutdated: true`.

Errors: 401 `UNAUTHORIZED` · 404 `SUBJECT_NOT_FOUND` / `UNIT_NOT_FOUND` / `TOPIC_NOT_FOUND`, e.g.

```json
{"error": {"code": "UNIT_NOT_FOUND", "message": "Unit 'u99' not found"}}
```

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
| GET | `/api/v1/questions/{id}` | ✅ One question with options (no answer key, no explanation). Approved or my own only, else `QUESTION_NOT_FOUND` |
| GET | `/api/v1/topics/{id}/questions` | ✅ Approved practice questions for a topic (`limit` 1-50, default 10) |
| POST | `/api/v1/questions/{id}/explain` | ✅ `{selected_option_id?}` → `{question_id, explanation}` (sync AI call, after answering) |

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
| POST | `/api/v1/papers/generate-by-units` | ✅ `{units: [1-10], num_questions, title?}` → paper; questions spread over the units, each labelled "Unit N: title" (`INVALID_UNITS`, `UNIT_NOT_FOUND`, `NO_QUESTIONS_GENERATED`) |
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
| GET | `/api/v1/insights/summary` | ✅ My overview: overall mastery + weekly change, MCQ score, topic levels, streak and study days |
| GET | `/api/v1/insights/units` | ✅ My mastery per unit (0-100) with grade, weekly change, strongest / weakest unit |
| GET | `/api/v1/insights/concepts` | Weakest concepts |
| GET | `/api/v1/mistakes` | ✅ My wrong MCQ answers, newest first, paged (`?type=`, `?unit_id=`, `?status=open\|resolved`) |
| PATCH | `/api/v1/mistakes/{id}` | ✅ `{resolved}` → mark a mistake fixed or open again |
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
| `dashboard_admin.py` | Samni | `/admin/dashboard` | ✅ dashboard: KPIs, 14-day activity, newest reports, most missed topics (below) |
| `content_admin.py` | Samni | `/admin/content` | ✅ content library: notes, short notes, diagrams; approve / reject / edit (below) |
| `rag_admin.py` | Samni | `/admin/rag` | ✅ `GET/POST /sources`, `POST /reindex` (below); `/documents` are older placeholders |
| `questions_admin.py` | Udith | `/admin/questions` | ✅ question bank + editor, quality review, past papers (below) |
| `knowledge_admin.py` | Keshomigha | `/admin/model-answers` | ✅ model answers, marking points, keywords (below) |
| `syllabus_admin.py` | Keshomigha | `/admin/syllabus` | ✅ units / topics / concepts: list (outdated included), add, edit, mark outdated; delete only empty + unused topics/concepts (units are never deleted) |
| `analytics_admin.py` | Keshomigha | `/admin/analytics` | ✅ `GET /overview`, `/performance`, `/ai-usage` (all with `?days=`, default 30): student activity, average mastery per unit, most-missed topics, misconceptions, AI requests per feature and day |
| `moderation_admin.py` | Mogith | `/admin/moderation`, `/admin/community` | ✅ reports queue (posts, replies, visuals) + resolve, study groups (below) |
| `users_admin.py` | Mogith | `/admin/users` | ✅ Students list + suspend / reinstate (below) |

### Admin: students (`users_admin.py`)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/admin/users?search=&exam_year=&status=active\|suspended\|inactive&district=&page=&page_size=` | ✅ `{items: [{id, full_name, email, school, district, exam_year, avg_mastery (0-100 or null), status, last_active_at}], total, active_total}`. Students only; `search` = name or email, any case; `page_size` 1-100 (default 20) |
| PATCH | `/api/v1/admin/users/{id}` | ✅ `{is_active}` → the row. `false` suspends (Firebase account disabled too, the student gets `USER_DISABLED`), `true` reinstates |

`status`: **suspended** = `is_active` false (wins over the others) · **inactive** = no study activity for 30+ days
(counted from sign-up if they never studied) · **active** = the rest. `active_total` = active students matching
the filters, ignoring `status`. `avg_mastery` = average of the newest mastery per unit. Every change is written to `audit_log`.

### Admin: moderation + study groups (`moderation_admin.py`)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/admin/moderation/reports` | ✅ Open reports, **one item per reported target**, oldest first: `[{id, target_type: post\|reply\|visual, target_id, reason, details, author_handle, group_name, text, visual_title, image_url, ai_flag_label, ai_flag_score (0-1 or null), report_count, created_at}]`. `id` = the oldest open report |
| POST | `/api/v1/admin/moderation/reports/{id}/resolve` | ✅ `{action: keep\|warn\|remove}` → 204. Closes every open report of that target. keep = dismiss · warn = in-app notification to the author + dismiss · remove = hide the post / reply (`moderation_status: removed`) or visual (`status: rejected`) |
| GET | `/api/v1/admin/community/groups` | ✅ `[{id, name, members, moderator_name (null = none), is_open}]`, by name |
| POST | `/api/v1/admin/community/groups` | ✅ `{name}` (2-120 characters) → 201 the group |

### Admin: content library (`content_admin.py`)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/admin/content?type=note\|short_note\|diagram&status=&unit=` | ✅ `[{id, title, type, syllabus_code ("5.4"), unit_number, status, is_ai_generated, model, prompt_version, body_markdown, image_url, auto_check, updated_at}]`, last changed first (max 200). No `status`: notes in every status except archived + diagrams waiting for review (draft / pending_review) |
| POST | `/api/v1/admin/content/{id}/approve` | ✅ optional `{note}` → the item. A diagram becomes `approved` (shared, `is_verified`); an older approved note of the same topic + kind is archived |
| POST | `/api/v1/admin/content/{id}/reject` | ✅ optional `{note}` → the item (`rejected`) |
| PATCH | `/api/v1/admin/content/{id}` | ✅ `{body_markdown}` → the note (version + 1). Diagrams: 409 `CONTENT_NOT_EDITABLE` |

`auto_check` is one sentence from the automatic checks (e.g. "No syllabus sources were cited..."), or null.
Diagrams' `body_markdown` is their Mermaid code in a mermaid code block.

### Admin: question bank + editor (`questions_admin.py`)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/admin/questions?unit=&type=mcq\|structured\|essay&difficulty=easy\|medium\|hard&status=&page=&page_size=` | ✅ `{items: [{id, code ("Q-1042"), stem, unit_number, topic_title, type, difficulty, source_year, is_ai_generated, status}], total, past_paper_percent}`, newest first. `status`: draft \| pending_review \| approved \| rejected \| archived \| outdated; without it archived ones are hidden |
| POST | `/api/v1/admin/questions/bulk` | ✅ `{ids (1-200), action: approve\|mark_outdated\|delete}` → 204. All or nothing. `delete` removes unused questions and **archives** ones students answered |
| GET | `/api/v1/admin/questions/{id}` | ✅ `{id, code, stem, type, difficulty, unit_id, topic_id, concept_id, explanation, status, is_ai_generated, options: [{label A-E, text, is_correct, misconception}]}` |
| POST | `/api/v1/admin/questions` | ✅ the same body without `id` / `code` → 201 the question |
| PUT | `/api/v1/admin/questions/{id}` | ✅ the same body → the question. Options are updated in place by label, so students' saved answers keep pointing at them |

Publishing (`status: "approved"`, or bulk approve) needs, for an MCQ: text on every option, exactly one correct option,
and a misconception on every wrong one. Otherwise 422 `QUESTION_INCOMPLETE` with the problems in
`details: [{field: "options.D.misconception", message}]`. Misconceptions are stored in `misconceptions` (one row per
text and concept, reused) and linked from `mcq_options.misconception_id`. `unit_id` / `topic_id` / `concept_id` must
belong together; a missing unit or topic is filled in from the level below. Outdated questions are hidden from students.

### Admin: quality review (`questions_admin.py` → quality module)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/admin/questions/quality` | ✅ `{in_queue, auto_check_failed, with_student_reports, avg_review_minutes, items: [{id, code, stem, unit_number, topic_code, checks: [{name, result: pass\|review\|fail, note}], student_reports: [{text, count}]}]}`. Items = AI questions waiting for review, oldest first |
| POST | `/api/v1/admin/questions/{id}/review` | ✅ `{approve}` → 204. true = approved (same publish rules as the editor), false = rejected. Saved as an admin `question_reviews` row |

The four checks, always in this order: **Single correct answer**, **Distractor quality**, **Syllabus match**,
**Duplicate check**. The newest AI review (`question_reviews.checks`, written by the REVIEW_QUESTIONS job) is used
when it has the check. Otherwise "Single correct answer" and "Duplicate check" are worked out from the data, and
the other two are `review` ("Not checked by the AI reviewer yet."). `avg_review_minutes` = average time from a
question's creation to an admin's decision over the last 30 days (null = none yet).

### Admin: past papers (`questions_admin.py`)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/admin/questions/past-papers` | ✅ `[{id, year, paper_type: paper_1_mcq\|paper_2_structured, scheme_linked, extraction: done\|running\|low_confidence\|failed, questions_extracted, progress (0-1), low_confidence, outdated_syllabus}]`, newest year first |
| POST | `/api/v1/admin/questions/past-papers` | ✅ multipart: `file` (PDF ≤ 40 MB), `year` (1990-2100), `paper_type`, optional `scheme` (marking scheme PDF) → 201 the paper with `extraction: "running"`. An EXTRACT_PAST_PAPER job runs in the background |
| GET | `/api/v1/admin/questions/past-papers/{id}/questions` | ✅ `[{id, label ("Q3 (b)"), marks, text, ocr_confidence (0-1), model_answer, keywords, suggested_keywords}]` in paper order |
| PUT | `/api/v1/admin/questions/past-papers/questions/{id}` | ✅ `{model_answer, keywords}` → the question (keywords trimmed, no repeats) |

Extraction (ai_service `pipelines/questions/past_paper_extract.py`, no LLM, free): PDF text layer + Tesseract OCR
for scanned pages → split at numbered questions ("12." / "12)"); Paper 2 is split again into parts "(a)", "(b)".
Marks come from "(4 marks)". `ocr_confidence` = share of normal-looking words; below 0.8 counts as
`low_confidence`. Progress: 0 queued → 0.2 reading → 0.9 saving → 1 done. The file type is checked from the bytes
(`%PDF-`), because Flutter web uploads PDFs as `application/octet-stream`.

### Admin: dashboard (`dashboard_admin.py`)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/admin/dashboard` | ✅ `{title: "Dashboard", message: null, batch_label: "A/L 2027 batch", kpis: [{kind, label, value, delta, trend: good\|bad\|warning, sparkline: [8 ints]}], activity: {day_labels: [14], quizzes: [14], notes_generated: [14]}, recent_reports: [{title, subtitle, meta, severity: high\|medium\|null}], missed_topics_attempts, missed_topics: [{topic, unit ("Unit 6 · Genetics"), miss_rate (0-1), attempts, top_misconception}]}` |

| KPI `kind` | `value` | `delta` / `trend` | `sparkline` (last 8 days) |
|---|---|---|---|
| `students` | students with study activity in the last 7 days | % vs the 7 days before; bad if down | active students per day |
| `quizzes` | quizzes / papers / diagnostics finished today | difference vs yesterday | finished per day |
| `aiReview` (camelCase on purpose) | AI questions + notes + diagrams waiting for review | "N older than 48h"; `warning` if N > 0 | AI questions + notes made per day |
| `reports` | open moderation items (one per reported target) | new reports today vs yesterday; bad if up | new reports per day |

`batch_label` = the exam year most students chose. `recent_reports` = the 5 newest open moderation items
(severity high: 3+ reports, AI score ≥ 0.9 or "offensive"; medium: 2 reports or AI score ≥ 0.7).
`missed_topics` = the 5 most missed topics of the last 30 days (same rule as `/admin/analytics/performance`) with
the misconception chosen most often there; `missed_topics_attempts` = all MCQ answers in those 30 days.
Admins' own activity is never counted. Day labels use Sri Lanka dates.

### Admin: MCQ → misconception mapping (`questions_admin.py`, placeholder screen in the app)

| Method | Path | Description |
|---|---|---|
| PUT | `/api/v1/admin/options/{option_id}/misconception` | ✅ `{misconception: "..." \| null}` → `{option_id, question_id, question_code, label, text, is_correct, misconception}`. null / "" removes the link; the same text is stored once per concept in `misconceptions` and reused |

### Admin: knowledge base / model answers (`knowledge_admin.py`, placeholder screen in the app)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/admin/model-answers?question_id=&status=` | ✅ `[ModelAnswerOut]`, last changed first (max 200) |
| POST | `/api/v1/admin/model-answers` | ✅ `{question_id, answer_text, source: marking_scheme\|admin\|ai, status: draft\|approved, points: [{text, marks, keywords: [..]}]}` → 201 `ModelAnswerOut`. One model answer per question |
| PUT | `/api/v1/admin/model-answers/{answer_id}/keywords` | ✅ `{points: [{point_id, keywords: [..]}]}` → `ModelAnswerOut`. Replaces the keywords of the listed points; other points keep theirs |

`ModelAnswerOut`: `{id, question_id, question_code, question_stem, answer_text, total_marks (sum of the points), source,
status, points: [{id, text, marks, keywords (A-Z)}], updated_at}`. Keywords are trimmed and de-duplicated (any case).

### Admin: RAG sources (`rag_admin.py`, placeholder screen in the app)

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/admin/rag/sources` | ✅ `[{id, title, source_type, unit_number, year, status: pending\|ingesting\|ready\|failed, chunk_count, page_count, error_message, indexed_at, updated_at}]` |
| POST | `/api/v1/admin/rag/sources` | ✅ multipart `file` (PDF / DOCX / TXT / MD, ≤ 40 MB), `title`, `source_type`, optional `unit_number`, `year` → 202 `{job_id, document_id}` (RAG_INGEST job) |
| POST | `/api/v1/admin/rag/reindex` | ✅ optional `{document_id}` → 202 `{job_id, document_id}`. No id = every document in one job (`{"all": true}`) |

Poll `GET /api/v1/jobs/{job_id}` for the job. Note: the ai_service reads the file from its own disk, so ingestion
works in dev (files under `LOCAL_STORAGE_DIR`); with `STORAGE_BUCKET` set, downloading the file in the ai_service is
still a TODO (`ai_service/rag/ingestion/pipeline.py`). The older placeholder routes `/admin/rag/documents` still exist.


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
| `AI_DAILY_LIMIT` | 422 / job `error_code` | all AI features | today's free AI allowance (whole app) is used up; try tomorrow |
| `FILE_NOT_FOUND` | 404 | visuals (dev file route) | no such stored image |
| `USER_NOT_FOUND` | 404 | admin users | unknown user id |
| `CANNOT_SUSPEND_SELF` | 400 | admin users | an admin tried to suspend their own account |
| `FIREBASE_ERROR` | 503 | admin users, auth | Firebase could not update the account; nothing was changed |
| `REPORT_NOT_FOUND` | 404 | admin moderation | unknown report id |
| `REPORT_ALREADY_RESOLVED` | 409 | admin moderation | the report was closed already |
| `GROUP_NAME_TAKEN` | 409 | admin community groups | a group with this name (any case) exists |
| `CONTENT_NOT_FOUND` | 404 | admin content | no note or visual with this id |
| `CONTENT_NOT_EDITABLE` | 409 | admin content | diagrams can't be edited as text |
| `QUESTION_NOT_FOUND` | 404 | questions, admin questions | unknown question id |
| `QUESTION_INCOMPLETE` | 422 | admin questions | can't publish yet; `details` lists the missing fields |
| `UNIT_NOT_FOUND` / `CONCEPT_NOT_FOUND` | 404 | admin questions | unknown unit / concept id in the editor |
| `SYLLABUS_MISMATCH` | 422 | admin questions | the topic is not in the unit, or the concept not in the topic |
| `PAST_PAPER_EXISTS` | 409 | admin past papers | this year + paper type is already uploaded |
| `PAST_PAPER_NOT_FOUND` / `PAST_PAPER_QUESTION_NOT_FOUND` | 404 | admin past papers | unknown paper / extracted question |
| `FILE_TOO_LARGE` | 413 | content, admin past papers | the file is over the limit (past papers: 40 MB) |
| `UNSUPPORTED_FILE_TYPE` | 415 | content, admin past papers | not a PDF |
| `EMPTY_FILE` | 422 | content, admin past papers | the uploaded file is empty |
| `NO_QUESTIONS_FOUND` | job `error` | admin past papers | no numbered questions were found in the PDF |
| `SOURCE_NOT_FOUND` | 404 | admin RAG | unknown source document id |
| `MODEL_ANSWER_EXISTS` | 409 | admin model answers | the question already has a model answer |
| `MODEL_ANSWER_NOT_FOUND` | 404 | admin model answers | unknown model answer id |
| `POINT_NOT_IN_ANSWER` | 422 | admin model answers | a `point_id` belongs to another model answer |
| `OPTION_NOT_FOUND` | 404 | admin MCQ mapping | unknown option id |
| `CORRECT_OPTION_NO_MISCONCEPTION` | 422 | admin MCQ mapping | the correct option can't have a misconception |

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
| (job) | `extract_past_paper` | ✅ Split a past paper PDF into questions (OCR for scanned pages) |
