"""Standard errors. EVERY error response has this shape:

    {"error": {"code": "SOME_CODE", "message": "Human readable text"}}

Validation errors also include "details" (the list of invalid fields), and an AppError can
add extra fields with `extra=`, e.g. {"error": {"code": "RESEND_TOO_SOON", ..., "retry_after": 42}}.

Raise `AppError` (or a subclass) anywhere in a service; the handlers below turn it into JSON.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base error for the whole API."""

    status_code = 400
    code = "BAD_REQUEST"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        extra: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        # Extra fields added inside "error", e.g. {"retry_after": 42} or {"missing": [...]}
        self.extra = extra or {}


class UnauthorizedError(AppError):
    status_code = 401
    code = "UNAUTHORIZED"


class ForbiddenError(AppError):
    status_code = 403
    code = "FORBIDDEN"


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"


class TooManyRequestsError(AppError):
    status_code = 429
    code = "TOO_MANY_REQUESTS"


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "SERVICE_UNAVAILABLE"


# Codes used when FastAPI/Starlette raises its own HTTPException (e.g. unknown URL -> 404)
_HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    429: "TOO_MANY_REQUESTS",
    501: "NOT_IMPLEMENTED",
    503: "SERVICE_UNAVAILABLE",
}


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    body = error_body(exc.code, exc.message)
    body["error"].update(exc.extra)
    headers = {}
    if "retry_after" in exc.extra:  # standard HTTP header for "try again in N seconds"
        headers["Retry-After"] = str(exc.extra["retry_after"])
    return JSONResponse(status_code=exc.status_code, content=body, headers=headers or None)


async def http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(code, str(exc.detail)),
        headers=getattr(exc, "headers", None),
    )


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    details = [
        {"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]}
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=error_body("VALIDATION_ERROR", "Request data is invalid", details),
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500, content=error_body("INTERNAL_ERROR", "Something went wrong")
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
