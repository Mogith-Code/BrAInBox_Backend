<p align="center"><img src="api/static/brand/logo_horizontal_1200.png" width="420"></p>

# BrAInBox Backend

> *Study smarter. Fix what matters.*: an AI study app for Sri Lankan **G.C.E. A/L Biology** students (English medium).

This repository contains the backend only. The Flutter mobile app and the admin portal live in **`brainbox-mobile`**.
The admin portal only uses the `/api/v1/admin/*` endpoints from here.

| Service | Folder | Port | What it does |
|---|---|---|---|
| **API** | `api/` | 8000 | Public REST API for the app and admin portal: auth checks, roles, business logic, DB writes |
| **AI service** | `ai_service/` | 8001 | Internal service, the **only** place that calls AI providers (Gemini, embeddings, OCR, images) and runs RAG |
| **Shared** | `shared/` | – | Settings, enums, branding and database models used by both |

Read next: [architecture](docs/architecture.md) · [folder structure](docs/folder-structure.md) ·
[planned endpoints](docs/api-endpoints.md) · [database](docs/database.md) · [RAG](ai_service/rag/README.md) ·
[contributing](CONTRIBUTING.md)

## Tech stack

Python 3.11 · FastAPI + Uvicorn · Pydantic v2 + pydantic-settings · SQLAlchemy 2 (async, asyncpg) · Alembic ·
PostgreSQL 15 + pgvector · firebase-admin · httpx · google-genai (Gemini) · google-cloud-vision · Jinja2 ·
pytest · ruff · mypy · pre-commit · Docker Compose

## Quick start (Docker)

```bash
cp .env.example .env                                   # works as-is: fake AI, no keys needed
docker compose up -d --build                           # db + api + ai_service
docker compose exec api alembic upgrade head           # create the tables
docker compose exec api python scripts/seed_syllabus.py
docker compose exec ai_service python scripts/ingest_documents.py
docker compose exec ai_service python scripts/rag_search.py --q "active transport" --unit 2
```

Then check:

```bash
curl localhost:8000/api/v1/health                      # {"status":"ok","db":"ok"}
curl -H "X-Service-Token: dev-service-token" localhost:8001/health
```

- API docs: <http://localhost:8000/docs> (Swagger) and <http://localhost:8000/redoc>
- AI service docs: <http://localhost:8001/docs>. Click **Authorize** and enter the service token.

`make up / down / migrate / seed / ingest / test / lint / fmt` are shortcuts for the commands above.

## Local development (without Docker for the Python code)

You still need a Postgres with pgvector. The easiest way is `docker compose up -d db`.

```bash
py -3.11 -m venv .venv            # Windows   (macOS/Linux: python3.11 -m venv .venv)
.venv\Scripts\activate            # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -e ".[api,ai,dev]"
pre-commit install
alembic upgrade head
uvicorn api.main:app --reload --port 8000
uvicorn ai_service.main:app --reload --port 8001
```

> Google libraries read `GOOGLE_APPLICATION_CREDENTIALS` from the **process environment**, not from `.env`.
> When you run outside Docker with real credentials, export it in your shell.

### Packaging: one `pyproject.toml` with extras

We use **one `pyproject.toml`** (not two requirements files), so versions and tool settings (ruff, mypy, pytest)
live in one place:

| Extra | Installs | Used by |
|---|---|---|
| *(base)* | FastAPI, SQLAlchemy, asyncpg, Alembic, pgvector, httpx, pydantic-settings | both services |
| `[api]` | firebase-admin, python-multipart | `api/Dockerfile` |
| `[ai]` | google-genai, google-cloud-vision, firebase-admin, jinja2, pypdf, python-docx | `ai_service/Dockerfile` |
| `[dev]` | pytest, pytest-asyncio, ruff, mypy, pre-commit | you + CI |

Each Docker image installs only its own extra, so the API image never contains AI SDKs.

## Tests

```bash
pytest                       # API + AI service tests; DB tests are skipped if no database is reachable
pytest -m db                 # only the database tests (need `alembic upgrade head` first)
ruff check . && ruff format --check .
mypy api ai_service shared
```

- `tests/conftest.py` replaces Firebase with fake users (`client` = student, `admin_client` = admin, `anon_client` = no token)
  and always uses the **fake AI providers**.
- Tests marked `@pytest.mark.db` use `TEST_DATABASE_URL`, or `DATABASE_URL` if that is not set. CI runs them against a pgvector service container.

## Rules

### Module layering rule

Every module in `api/modules/` has the same files:

```
router.py      HTTP endpoints only (validate, check role, call service)
schemas.py     Pydantic request/response models
service.py     business logic
repository.py  all SQL queries for this module
README.md      owner, purpose, endpoints, tables, Jira epic, git branch
```

1. Database models live in `shared/db/models/`, so both services can use them.
2. Modules call each other's **service** functions, never each other's repositories.
3. Only `api/core/ai_client.py` talks to the ai_service.
4. Only `ai_service/providers/` talks to external AI APIs.
5. Pipelines that need grounding use `ai_service/rag/retrieval/retriever.py` and never query `document_chunks` directly.

### API conventions

- All public routes are under **`/api/v1`**. Admin routes are under **`/api/v1/admin`** and require role **`admin`**.
- **Error format everywhere:** `{"error": {"code": "SOME_CODE", "message": "..."}}`. In the api, raise `AppError` (`api/core/errors.py`).
- Settings come only from environment variables. Every variable is documented in `.env.example`.
- **Never commit** `.env`, service-account JSON or copyrighted RAG documents.
- The app must start with no AI keys. The fakes in `ai_service/providers/fakes.py` take over.
- Prompts are versioned files (`*.v1.j2`). Change a prompt by adding `v2`, not by editing `v1`.
- Use `shared/branding.py` (`APP_NAME`, `TAGLINE`, colours, `LOGO_URL`) wherever the backend writes the app name.

## Team and ownership

| Member | Modules / folders |
|---|---|
| **Mogith** (22CSE0394) | auth, profiles, visuals, community, admin moderation + users, `ai_service/pipelines/visuals` + `community`, `.github/`, Docker + CI |
| **Samni** (22CSE0391) | content, admin content, admin RAG documents, `ai_service/rag/`, `ai_service/pipelines/summarization` + `notes` |
| **Udith** (22CSE0358) | questions, quizzes, exams, quality, recommendations, admin questions, `ai_service/pipelines/questions` + `recommendations` |
| **Keshomigha** (22CSE0392) | syllabus, evaluation, knowledge_base, performance, admin syllabus/knowledge/analytics, `shared/db/models`, migrations, `data/`, `ai_service/pipelines/evaluation` |

Owners are enforced through [`.github/CODEOWNERS`](.github/CODEOWNERS). Search for `TODO(<your name>)` to find your work.

## Configuration you must provide

| What | Where | Needed for |
|---|---|---|
| Firebase project id | `FIREBASE_PROJECT_ID` | verifying login tokens (every protected route) |
| Firebase service-account JSON | `./secrets/firebase-service-account.json` + `GOOGLE_APPLICATION_CREDENTIALS` | Storage signed URLs, Cloud Vision OCR |
| Storage bucket | `STORAGE_BUCKET` | uploads, generated images |
| Gemini API key | `GEMINI_API_KEY` + `USE_FAKE_AI=false` | real LLM / embeddings / images |
| Image provider | `IMAGE_PROVIDER` (`cloudflare` = free, default / `gemini` = paid), `CLOUDFLARE_ACCOUNT_ID` + `CLOUDFLARE_API_TOKEN` | AI illustrations (see `ai_service/pipelines/visuals/README.md`) |
| Free-tier caps | `GEMINI_DAILY_LIMIT`, `EMBEDDING_DAILY_LIMIT`, `IMAGE_DAILY_LIMIT`, `OCR_DAILY_LIMIT` | stop AI calls before the free allowance runs out (`ai_service/daily_limits.py`) |
| Kroki server | `KROKI_URL` (default `https://kroki.io`, no key) | Mermaid diagrams → PNG |
| Visual limit | `VISUALS_DAILY_LIMIT` (default 20) | visuals per student per 24 hours |
| YouTube API key | `YOUTUBE_API_KEY` | recommendations |
| Service token | `AI_SERVICE_TOKEN` (long random value outside dev) | api → ai_service |
| GitHub handles | `.github/CODEOWNERS` | review assignment |
