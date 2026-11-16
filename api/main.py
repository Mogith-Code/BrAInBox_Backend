"""BrAInBox public REST API.

Run locally:   uvicorn api.main:app --reload --port 8000
Docs:          http://localhost:8000/docs   and   http://localhost:8000/redoc
"""

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from api.core.config import get_settings
from api.core.database import SessionDep
from api.core.errors import register_error_handlers
from api.modules.admin.router import router as admin_router
from api.modules.auth.router import router as auth_router
from api.modules.community.router import router as community_router
from api.modules.content.router import router as content_router
from api.modules.evaluation.router import router as evaluation_router
from api.modules.exams.router import legacy_router as exams_legacy_router
from api.modules.exams.router import router as exams_router
from api.modules.home.router import router as home_router
from api.modules.jobs.router import router as jobs_router
from api.modules.knowledge_base.router import router as knowledge_base_router
from api.modules.learn.router import router as learn_router
from api.modules.performance.router import router as performance_router
from api.modules.profiles.router import router as profiles_router
from api.modules.quality.router import router as quality_router
from api.modules.questions.router import router as questions_router
from api.modules.quizzes.router import router as quizzes_router
from api.modules.recommendations.router import router as recommendations_router
from api.modules.syllabus.router import router as syllabus_router
from api.modules.visuals.router import router as visuals_router
from shared.branding import APP_NAME, FAVICON_32_PATH, LOGO_URL, TAGLINE

API_PREFIX = "/api/v1"
STATIC_DIR = Path(__file__).parent / "static"

# Order here = order of the groups in /docs
MODULE_ROUTERS = [
    auth_router,
    profiles_router,
    home_router,
    syllabus_router,
    learn_router,
    content_router,
    visuals_router,
    questions_router,
    quizzes_router,
    exams_router,
    quality_router,
    evaluation_router,
    knowledge_base_router,
    performance_router,
    recommendations_router,
    community_router,
    jobs_router,
    admin_router,
]

logger = logging.getLogger(__name__)


def check_production_settings(settings: Any) -> None:
    """Refuse to start in production with settings that are only safe on a laptop."""
    problems = []
    if settings.AI_SERVICE_TOKEN in ("", "dev-service-token"):
        problems.append("AI_SERVICE_TOKEN must be a long random secret")
    if settings.AUTH_CODE_SECRET in ("", "dev-only-change-me"):
        problems.append("AUTH_CODE_SECRET must be a long random secret")
    if not settings.FIREBASE_PROJECT_ID:
        problems.append("FIREBASE_PROJECT_ID is empty (logins cannot be checked)")
    if not settings.STORAGE_BUCKET:
        problems.append("STORAGE_BUCKET is empty (uploads have nowhere to go)")
    if settings.EMAIL_BACKEND == "console":
        problems.append(
            "EMAIL_BACKEND=console would print verification codes instead of sending them"
        )
    if settings.DEV_EXPOSE_CODES or settings.DEBUG_SHOW_ANSWERS:
        problems.append("DEV_EXPOSE_CODES and DEBUG_SHOW_ANSWERS must be false")
    if "*" in settings.CORS_ORIGINS and "localhost" not in settings.CORS_ORIGINS:
        problems.append("CORS_ORIGINS must list the real origins, not a wildcard")
    if settings.JOB_RUNNER == "cloudtasks" and not settings.JOBS_TARGET_URL:
        problems.append("JOBS_TARGET_URL is needed with JOB_RUNNER=cloudtasks")
    if problems:
        raise RuntimeError("Unsafe production settings: " + "; ".join(problems))


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.LOG_LEVEL)
    if settings.DEV_LOGIN_ENABLED:
        if settings.ENVIRONMENT != "dev":
            # The dev login lets anyone in as admin; never allow it on a real server.
            raise RuntimeError("DEV_LOGIN_ENABLED=true is only allowed with ENVIRONMENT=dev")
        logger.warning("DEV LOGIN IS ON: 'Bearer dev-admin' is an admin (this computer only)")

    app = FastAPI(
        title=f"{APP_NAME} API",
        description=(
            f"**{TAGLINE}**\n\n"
            "REST API for the BrAInBox mobile app and admin portal "
            "(G.C.E. A/L Biology). All routes are under `/api/v1`; "
            "admin routes are under `/api/v1/admin` and need the `admin` role.\n\n"
            "Authenticate with `Authorization: Bearer <Firebase ID token>`."
        ),
        version=settings.API_VERSION,
        # We serve our own branded docs pages below.
        docs_url=None,
        redoc_url=None,
    )

    # --- CORS (mobile web build + admin portal)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_exact_origins(),
        allow_origin_regex=settings.cors_origin_regex(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_error_handlers(app)

    # --- Static brand files (favicon, logo) used by the docs pages
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # --- Routes
    @app.get(f"{API_PREFIX}/health", tags=["Health"], summary="Health check (API + database)")
    async def health(session: SessionDep, response: Response) -> dict[str, str]:
        try:
            await session.execute(text("SELECT 1"))
            db_status = "ok"
        except Exception:
            logger.exception("Database health check failed")
            db_status = "error"
            response.status_code = 503
        return {"status": "ok" if db_status == "ok" else "degraded", "db": db_status}

    for router in MODULE_ROUTERS:
        app.include_router(router, prefix=API_PREFIX)

    # Old URLs of Udith's standalone exam app (/exam/*, no /api/v1): see exams/router.py
    app.include_router(exams_legacy_router)

    _add_branded_docs(app)
    return app


def _add_branded_docs(app: FastAPI) -> None:
    """Swagger UI at /docs and ReDoc at /redoc with the BrAInBox favicon, title and logo."""
    docs_title = f"{app.title} – Docs"

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title, version=app.version, description=app.description, routes=app.routes
        )
        # ReDoc shows this logo at the top of the sidebar.
        schema["info"]["x-logo"] = {"url": LOGO_URL, "altText": APP_NAME}
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]

    @app.get("/docs", include_in_schema=False)
    async def swagger_docs() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url=app.openapi_url or "/openapi.json",
            title=docs_title,
            swagger_favicon_url=FAVICON_32_PATH,
        )

    @app.get("/redoc", include_in_schema=False)
    async def redoc_docs() -> HTMLResponse:
        return get_redoc_html(
            openapi_url=app.openapi_url or "/openapi.json",
            title=docs_title,
            redoc_favicon_url=FAVICON_32_PATH,
        )


# Checked once when the server starts (uvicorn api.main:app), not for every test app.
if get_settings().ENVIRONMENT == "prod":
    check_production_settings(get_settings())

app = create_app()
