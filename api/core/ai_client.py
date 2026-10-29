"""The ONLY place in the api that talks to the internal ai_service.

Every request carries the shared secret in the `X-Service-Token` header.

Errors:
  * 422 with a pipeline error code (e.g. EMPTY_NOTES) -> AppError with that code and message,
    because the student's input is the problem (ai_service/errors.py)
  * anything else (down, timeout, 5xx, our own bad request) -> 503 AI_SERVICE_UNAVAILABLE
"""

import logging
from typing import Annotated, Any

import httpx
from fastapi import Depends

from api.core.config import get_settings
from api.core.errors import AppError, ServiceUnavailableError

logger = logging.getLogger(__name__)

SERVICE_TOKEN_HEADER = "X-Service-Token"


class AIClient:
    def __init__(self, base_url: str, token: str, timeout: float = 60.0):
        self._base_url = base_url
        self._headers = {SERVICE_TOKEN_HEADER: token}
        self._timeout = timeout

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, headers=self._headers, timeout=self._timeout
            ) as client:
                response = await client.post(path, json=payload)
                response.raise_for_status()
                data: dict[str, Any] = response.json()
                return data
        except httpx.HTTPStatusError as exc:
            input_error = input_error_from(exc.response)
            if input_error is not None:
                raise input_error from exc
            logger.warning("ai_service call %s failed: %s", path, exc)
            raise _unavailable() from exc
        except httpx.HTTPError as exc:
            logger.warning("ai_service call %s failed: %s", path, exc)
            raise _unavailable() from exc

    async def health(self) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=self._base_url, headers=self._headers, timeout=5
        ) as client:
            response = await client.get("/health")
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            return data

    async def run_job(self, job_id: str, job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Ask the ai_service to run one AI job (see ai_service/routes/jobs.py)."""
        return await self._post(
            "/jobs/run", {"job_id": job_id, "job_type": job_type, "payload": payload}
        )

    async def sync(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Fast AI calls that answer immediately, e.g. name="explain-mcq"."""
        return await self._post(f"/sync/{name}", payload)


def _unavailable() -> ServiceUnavailableError:
    return ServiceUnavailableError(
        "The AI service is not available right now", code="AI_SERVICE_UNAVAILABLE"
    )


def input_error_from(response: httpx.Response) -> AppError | None:
    """The student's input error from an ai_service response, or None if it is not one.

    Only 422 answers with a pipeline code count. 422 VALIDATION_ERROR means the api sent a bad
    request (our bug, not the student's), so it stays a 503.
    """
    if response.status_code != 422:
        return None
    try:
        error = response.json()["error"]
        code, message = str(error["code"]), str(error["message"])
    except (ValueError, KeyError, TypeError):
        return None
    if code == "VALIDATION_ERROR":
        return None
    return AppError(message, code=code, status_code=422)


def get_ai_client() -> AIClient:
    """FastAPI dependency (tests override it with a fake)."""
    settings = get_settings()
    return AIClient(
        settings.AI_SERVICE_URL, settings.AI_SERVICE_TOKEN, settings.AI_SERVICE_TIMEOUT_SECONDS
    )


AIClientDep = Annotated[AIClient, Depends(get_ai_client)]
