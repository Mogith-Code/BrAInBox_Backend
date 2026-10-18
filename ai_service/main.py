"""BrAInBox internal AI service.

Run locally:   uvicorn ai_service.main:app --reload --port 8001
Every request (including /health) must send:  X-Service-Token: <AI_SERVICE_TOKEN>
Only the docs pages (/docs, /redoc, /openapi.json) and /static are open, for developers.
"""

import hmac
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from ai_service.config import get_settings
from ai_service.providers import provider_names
from ai_service.routes import jobs, sync
from shared.branding import APP_NAME, FAVICON_32_PATH, LOGO_URL, TAGLINE

SERVICE_TOKEN_HEADER = "X-Service-Token"
OPEN_PATHS = ("/docs", "/redoc", "/openapi.json", "/static/")
STATIC_DIR = Path(__file__).parent / "static"

logger = logging.getLogger(__name__)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.LOG_LEVEL)

    app = FastAPI(
        title=f"{APP_NAME} AI Service (internal)",
        description=(
            f"**{TAGLINE}**\n\nInternal service: the only place that calls AI providers. "
            f"Every request needs the `{SERVICE_TOKEN_HEADER}` header. "
            f"Fake providers active: **{settings.use_fakes}**."
        ),
        version=settings.API_VERSION,
        docs_url=None,
        redoc_url=None,
    )

    @app.middleware("http")
    async def require_service_token(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        if path.startswith(OPEN_PATHS):
            return await call_next(request)
        sent = request.headers.get(SERVICE_TOKEN_HEADER, "")
        expected = settings.AI_SERVICE_TOKEN
        # compare_digest avoids leaking the token through timing differences
        if not expected or not hmac.compare_digest(sent.encode(), expected.encode()):
            return _error(401, "INVALID_SERVICE_TOKEN", "Missing or invalid service token")
        return await call_next(request)

    # --- Standard error format: {"error": {"code", "message"}}
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error(exc.status_code, "HTTP_ERROR", str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error(422, "VALIDATION_ERROR", str(exc.errors()))

    @app.exception_handler(NotImplementedError)
    async def not_implemented(request: Request, exc: NotImplementedError) -> JSONResponse:
        return _error(501, "NOT_IMPLEMENTED", str(exc) or "Not implemented yet")

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s", request.url.path)
        return _error(500, "INTERNAL_ERROR", "AI service error")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/health", tags=["Health"], summary="Health check (needs the service token)")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "fake_ai": settings.use_fakes, "providers": provider_names()}

    app.include_router(sync.router)
    app.include_router(jobs.router)

    _add_branded_docs(app)
    return app


def _add_branded_docs(app: FastAPI) -> None:
    docs_title = f"{app.title} – Docs"

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title, version=app.version, description=app.description, routes=app.routes
        )
        schema["info"]["x-logo"] = {"url": LOGO_URL, "altText": APP_NAME}
        # Lets you authorise in Swagger UI with the service token.
        schema.setdefault("components", {})["securitySchemes"] = {
            "ServiceToken": {"type": "apiKey", "in": "header", "name": SERVICE_TOKEN_HEADER}
        }
        schema["security"] = [{"ServiceToken": []}]
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]

    @app.get("/docs", include_in_schema=False)
    async def swagger_docs() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url="/openapi.json", title=docs_title, swagger_favicon_url=FAVICON_32_PATH
        )

    @app.get("/redoc", include_in_schema=False)
    async def redoc_docs() -> HTMLResponse:
        return get_redoc_html(
            openapi_url="/openapi.json", title=docs_title, redoc_favicon_url=FAVICON_32_PATH
        )


app = create_app()
