# `admin` module

Admin-only endpoints for the admin web portal (Flutter web, in the `brainbox-mobile` repo).
Everything here is mounted under **`/api/v1/admin`** and requires role **`admin`**
(the check is added once in `router.py`).

| | |
|---|---|
| **Owner** | Each file has its own owner (below). `router.py`, `service.py` (audit log): Mogith |
| **Purpose** | Manage content, questions, syllabus, knowledge base, RAG documents, users and moderation |
| **Tables** | `audit_log` (own) + the tables of the modules it manages, via their services |
| **Jira epic** | BRN-E16 Admin Portal *(placeholder key – replace with the real one)* |
| **Git branch** | `feature/admin` (tasks: `feature/admin/BRN-xx-short-name`) |

## Files and owners

| File | Owner | Prefix | Planned endpoints |
|---|---|---|---|
| `dashboard_admin.py` | Samni | `/admin/dashboard` | ✅ KPIs, 14-day activity, newest reports, most missed topics (built in `service.build_dashboard`) |
| `content_admin.py` | Samni | `/admin/content` | ✅ content library (notes, short notes, diagrams waiting for review), approve / reject / edit |
| `rag_admin.py` | Samni | `/admin/rag` | ✅ sources list + upload (RAG_INGEST job) + reindex one or all |
| `questions_admin.py` | Udith | `/admin/questions` | ✅ question bank + editor (publish rules, bulk actions); quality review and past papers (see below) |
| `knowledge_admin.py` | Keshomigha | `/admin/model-answers` | ✅ model answers with marking points + keywords |
| `syllabus_admin.py` | Keshomigha | `/admin/syllabus` | ✅ units / topics / concepts manager (details in `syllabus/README.md`) |
| `analytics_admin.py` | Keshomigha | `/admin/analytics` | ✅ usage, performance, AI usage (details in `performance/README.md`) |
| `moderation_admin.py` | Mogith | `/admin/moderation`, `/admin/community` | ✅ reports queue (posts, replies, visuals, grouped per target), resolve keep/warn/remove, study groups |
| `users_admin.py` | Mogith | `/admin/users` | ✅ students list (search, filters, status, avg mastery) + suspend / reinstate |

Placeholders right now: `GET /api/v1/admin/<area>/status` → `{"module": "<file>", "status": "todo"}`.

## Rules

- Admin route files are routers only. They call the **service** of the module that owns the data
  (e.g. `api.modules.content.service`), never another module's repository.
- Every admin action that changes data writes an `audit_log` row with `service.record_audit(...)`.
- Tests: `tests/api/test_admin.py`.
