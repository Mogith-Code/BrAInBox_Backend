# Database

PostgreSQL 15 + **pgvector**. Models: `shared/db/models/` (one file per area, all imported in `__init__.py`).
Migrations: `migrations/versions/` (Alembic, async). Schema owner: **Keshomigha**.

Conventions:
- Every table has a UUID primary key `id` (`gen_random_uuid()`) plus `created_at` / `updated_at`, except the link table `question_concepts`.
- Every foreign key has an index. User-owned rows use `ON DELETE CASCADE`; `created_by`-style columns use `SET NULL`.
- Enums (`shared/enums.py`) are stored as `VARCHAR(32)` with no database check, so new values need no migration.
- Embeddings are `vector(768)`. `document_chunks` has an **HNSW** index (cosine) and a **GIN** index on the generated `tsv` column.

## Workflow for a schema change

```bash
# 1. edit / add a model in shared/db/models/ (and import it in __init__.py)
alembic revision --autogenerate -m "add xyz"   # 2. generate
# 3. READ the generated file in migrations/versions/ and fix it if needed
alembic upgrade head                           # 4. apply
alembic check                                  # 5. CI also runs this: models == migrations
```

## Tables per area

### `user.py` — owner Mogith (logic) / Keshomigha (schema) — used by: auth, profiles

| Table | Purpose | Main columns | References |
|---|---|---|---|
| `users` | One row per Firebase account (students and admins). | firebase_uid, email, display_name, role, is_active, last_login_at | - |
| `student_profiles` | Extra details for a student (one profile per user). | school, district, exam_year, avatar_url, bio | `user_id` → users |

### `syllabus.py` — owner Keshomigha — used by: syllabus

| Table | Purpose | Main columns | References |
|---|---|---|---|
| `units` | One of the 10 A/L Biology units. | number, title, description | - |
| `topics` | A topic inside a unit, e.g. "2.3 Cell membrane". | number, title, description, order_index | `unit_id` → units |
| `concepts` | A single idea students must master, e.g. "active transport". | name, description, embedding | `topic_id` → topics |

### `content.py` — owner Samni — used by: content

| Table | Purpose | Main columns | References |
|---|---|---|---|
| `notes` | Topic notes (full or short), AI-generated or written by an admin. | title, note_type, body_md, status, prompt_version, citations | `created_by` → users<br>`topic_id` → topics |
| `uploads` | A file a student uploaded (PDF, image...) to be summarised. | file_name, file_path, mime_type, size_bytes, processing_status | `topic_id` → topics<br>`user_id` → users |
| `summaries` | AI summary of an upload (or of a topic). | body_md, prompt_version | `topic_id` → topics<br>`upload_id` → uploads<br>`user_id` → users |
| `library_items` | Something a student saved to their library (note, summary, visual...). | item_type, item_id, title | `user_id` → users |

### `visual.py` — owner Mogith — used by: visuals

| Table | Purpose | Main columns | References |
|---|---|---|---|
| `visuals` |  | kind, title, mermaid_code, image_path, prompt, prompt_version, status | `concept_id` → concepts<br>`created_by` → users<br>`topic_id` → topics |
| `visual_reports` | A student reports a wrong or unclear visual. | reason, details, status | `user_id` → users<br>`visual_id` → visuals |

### `question.py` — owner Udith — used by: questions

| Table | Purpose | Main columns | References |
|---|---|---|---|
| `questions` |  | question_type, difficulty, stem, explanation, marks, source, year, status, prompt_version | `created_by` → users<br>`topic_id` → topics |
| `misconceptions` | A common wrong idea. Wrong MCQ options point to one, so mistakes can be explained. | title, description | `concept_id` → concepts |
| `mcq_options` |  | label, text, is_correct | `misconception_id` → misconceptions<br>`question_id` → questions |
| `question_concepts` | Many-to-many link: which concepts a question tests. |  | `concept_id` → concepts<br>`question_id` → questions |

### `quality.py` — owner Udith — used by: quality

| Table | Purpose | Main columns | References |
|---|---|---|---|
| `question_reviews` |  | reviewer_type, verdict, score, comments, prompt_version | `question_id` → questions<br>`reviewer_id` → users |
| `question_reports` | A student reports a wrong / unclear question. | reason, details, status | `question_id` → questions<br>`user_id` → users |
| `question_stats` | Running statistics for one question (one row per question). | attempts_count, correct_count, avg_time_seconds, discrimination_index | `question_id` → questions |

### `exam.py` — owner Udith — used by: quizzes, exams

| Table | Purpose | Main columns | References |
|---|---|---|---|
| `papers` |  | title, paper_type, year, duration_minutes, total_marks, status | `created_by` → users<br>`unit_id` → units |
| `paper_questions` |  | position, marks | `paper_id` → papers<br>`question_id` → questions |
| `attempts` | A student taking a paper / quiz once. | status, started_at, submitted_at, score | `paper_id` → papers<br>`user_id` → users |
| `responses` | The student's answer to one question inside an attempt. | answer_text, answer_image_path, is_correct, marks_awarded, time_spent_seconds | `attempt_id` → attempts<br>`question_id` → questions<br>`selected_option_id` → mcq_options |

### `knowledge.py` — owner Keshomigha — used by: knowledge_base

| Table | Purpose | Main columns | References |
|---|---|---|---|
| `model_answers` |  | answer_text, total_marks, source, status | `created_by` → users<br>`question_id` → questions |
| `answer_points` | One marking point of a model answer (e.g. "mentions ATP is used" = 1 mark). | point_text, marks, order_index | `model_answer_id` → model_answers |
| `keywords` | A keyword (with synonyms) that shows an answer point was made. | keyword, synonyms, weight | `answer_point_id` → answer_points |

### `evaluation.py` — owner Keshomigha — used by: evaluation

| Table | Purpose | Main columns | References |
|---|---|---|---|
| `evaluations` |  | answer_text, answer_image_path, ocr_text, estimated_marks, max_marks, matched_points, feedback, status, prompt_version | `question_id` → questions<br>`response_id` → responses<br>`user_id` → users |

### `performance.py` — owner Keshomigha — used by: performance

| Table | Purpose | Main columns | References |
|---|---|---|---|
| `mistakes` |  | mistake_type, note | `concept_id` → concepts<br>`misconception_id` → misconceptions<br>`question_id` → questions<br>`response_id` → responses<br>`user_id` → users |
| `concept_mastery` | How well one student knows one concept (0.0 - 1.0). | mastery_score, attempts_count, last_practiced_at | `concept_id` → concepts<br>`user_id` → users |

### `recommendation.py` — owner Udith — used by: recommendations

| Table | Purpose | Main columns | References |
|---|---|---|---|
| `resources` | An external or internal resource (YouTube video, article, note). | title, url, resource_type, provider, external_id, duration_seconds, status | `concept_id` → concepts<br>`topic_id` → topics |
| `recommendations` |  | reason, score, is_dismissed | `concept_id` → concepts<br>`resource_id` → resources<br>`user_id` → users |
| `study_plans` |  | title, start_date, end_date, is_active | `user_id` → users |
| `plan_items` |  | title, due_date, is_done, order_index | `resource_id` → resources<br>`study_plan_id` → study_plans<br>`topic_id` → topics |

### `community.py` — owner Mogith — used by: community

| Table | Purpose | Main columns | References |
|---|---|---|---|
| `community_groups` |  | name, description, is_private | `created_by` → users<br>`unit_id` → units |
| `group_members` |  | role | `group_id` → community_groups<br>`user_id` → users |
| `posts` |  | title, body, tags, moderation_status | `author_id` → users<br>`group_id` → community_groups<br>`topic_id` → topics |
| `replies` |  | body, is_ai_suggested, is_accepted, moderation_status | `author_id` → users<br>`post_id` → posts |
| `votes` | +1 / -1 on a post OR a reply (exactly one of post_id / reply_id is set). | value | `post_id` → posts<br>`reply_id` → replies<br>`user_id` → users |
| `content_reports` | A user reports a post or reply for moderation. | target_type, target_id, reason, details, status | `reporter_id` → users<br>`reviewed_by` → users |

### `rag.py` — owner Keshomigha (schema) / Samni (RAG) — used by: admin/rag_admin, ai_service/rag

| Table | Purpose | Main columns | References |
|---|---|---|---|
| `source_documents` |  | title, source_type, file_path, sha256, status, year, chunk_count, error_message | `unit_id` → units<br>`uploaded_by` → users |
| `document_chunks` |  | chunk_index, text, heading_path, page, tsv, embedding | `concept_id` → concepts<br>`document_id` → source_documents<br>`topic_id` → topics<br>`unit_id` → units |

### `system.py` — owner shared — used by: jobs, admin, ai_service

| Table | Purpose | Main columns | References |
|---|---|---|---|
| `ai_jobs` | A long-running AI task. The app polls GET /api/v1/jobs/{id} for its status. | job_type, status, input, result, error, attempts, started_at, finished_at | `requested_by` → users |
| `ai_usage_log` | One row per call to an AI provider (tokens, latency, cost). | provider, model, operation, prompt_name, input_tokens, output_tokens, latency_ms, cost_usd, success | `job_id` → ai_jobs |
| `audit_log` | Who did what in the admin portal. | action, target_type, target_id, details, ip_address | `actor_id` → users |
