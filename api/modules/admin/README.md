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
| `content_admin.py` | Samni | `/admin/content` | notes CRUD, approve/reject, trigger note generation |
| `rag_admin.py` | Samni | `/admin/rag` | `POST /documents` (upload + RAG_INGEST job), `GET /documents`, `POST /documents/{id}/reindex` |
| `questions_admin.py` | Udith | `/admin/questions` | question bank, MCQ → misconception mapping, quality review queue, past papers |
| `knowledge_admin.py` | Keshomigha | `/admin/knowledge` | model answers, answer points, keywords |
| `syllabus_admin.py` | Keshomigha | `/admin/syllabus` | units / topics / concepts CRUD |
| `analytics_admin.py` | Keshomigha | `/admin/analytics` | usage, performance, AI cost |
| `moderation_admin.py` | Mogith | `/admin/moderation` | reports queue (posts, replies, visuals) |
| `users_admin.py` | Mogith | `/admin/users` | list users, change role, disable |

Placeholders right now: `GET /api/v1/admin/<area>/status` → `{"module": "<file>", "status": "todo"}`.

## Rules

- Admin route files are routers only. They call the **service** of the module that owns the data
  (e.g. `api.modules.content.service`), never another module's repository.
- Every admin action that changes data should write an `audit_log` row (`service.py`, TODO).
- Tests: `tests/api/test_admin.py`.
