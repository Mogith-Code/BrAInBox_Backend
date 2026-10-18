# Folder structure

```
brainbox-backend/
├── api/                      SERVICE 1 – public REST API (FastAPI, :8000)
│   ├── main.py               app factory, CORS, error handlers, routers, /api/v1/health, branded /docs + /redoc
│   ├── static/brand/         favicon + logo used by the docs pages
│   ├── core/                 cross-cutting: config, database, security, errors, pagination, jobs, ai_client, storage
│   └── modules/<module>/     router.py · schemas.py · service.py · repository.py · README.md
│       └── admin/            admin-only routers, one file per area (router.py mounts them under /admin)
│
├── ai_service/               SERVICE 2 – internal AI service (FastAPI, :8001)
│   ├── main.py               service-token check, /health, branded docs
│   ├── config.py             model names, limits, RAG settings
│   ├── routes/               sync.py (fast calls) · jobs.py (POST /jobs/run → pipeline)
│   ├── providers/            one adapter per external AI API + fakes.py
│   ├── rag/                  shared retrieval layer (ingestion / indexing / retrieval / context_builder)
│   ├── pipelines/<feature>/  one folder per AI feature, each with README.md (owner)
│   ├── prompts/<feature>/    versioned Jinja2 templates (*.v1.j2)
│   ├── schemas/              Pydantic models for LLM outputs + HTTP bodies
│   └── evals/                offline evaluation sets + scripts
│
├── shared/                   used by both services
│   ├── settings.py           base settings (env vars / .env)
│   ├── branding.py           APP_NAME, TAGLINE, colours, LOGO_URL
│   ├── enums.py              UserRole, JobType, ...
│   └── db/                   base.py (Base + mixins) · session.py · models/ (one file per area)
│
├── migrations/               Alembic (async) – versions/0001_initial_schema.py
├── data/                     seed data (syllabus JSON, RAG sources – not committed if copyrighted)
├── scripts/                  CLI tools: seed, ingest, rag_search, imports, evals
├── tests/                    pytest: api/ (one file per module), ai_service/ (incl. rag/)
├── docs/                     architecture, folder structure, endpoints, database
├── design/brand/             brand pack (svg/ + png/) – source of the logo files
└── .github/                  CI workflow, PR template, CODEOWNERS
```

## Where does my code go?

| I want to... | Put it in |
|---|---|
| add an endpoint | `api/modules/<module>/router.py` (+ schema in `schemas.py`) |
| add business logic | `api/modules/<module>/service.py` |
| write a SQL query | `api/modules/<module>/repository.py` |
| add / change a table | `shared/db/models/<area>.py`, then `alembic revision --autogenerate` |
| use another module's data | call `api.modules.<other>.service`, **not** its repository |
| call an AI model | an `ai_service/pipelines/<feature>/` file, via `ai_service.providers.get_llm()` etc. |
| ground an AI answer in sources | `ai_service.rag.retrieval.retriever.retrieve` + `rag.context_builder.build_context` |
| add an AI job type | `shared/enums.JobType`, plus a pipeline `run()`, plus an entry in `ai_service/routes/jobs.py:DISPATCH` |
| write a prompt | `ai_service/prompts/<feature>/<name>.v1.j2` |
| add an admin screen's API | `api/modules/admin/<area>_admin.py` |
| add a setting | `shared/settings.py` (both services) or `api/core/config.py` / `ai_service/config.py`, plus `.env.example` |
