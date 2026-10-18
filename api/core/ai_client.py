"""The ONLY place in the api that talks to the internal ai_service.

Every request carries the shared secret in the `X-Service-Token` header.
"""

import logging
from typing import Annotated, Any

import httpx
from fastapi import Depends

from api.core.config import get_settings
from api.core.errors import ServiceUnavailableError

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
        except httpx.HTTPError as exc:
            logger.warning("ai_service call %s failed: %s", path, exc)
            raise ServiceUnavailableError(
                "The AI service is not available right now", code="AI_SERVICE_UNAVAILABLE"
            ) from exc

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


def get_ai_client() -> AIClient:
    """FastAPI dependency (tests override it with a fake)."""
    settings = get_settings()
    return AIClient(
        settings.AI_SERVICE_URL, settings.AI_SERVICE_TOKEN, settings.AI_SERVICE_TIMEOUT_SECONDS
    )


AIClientDep = Annotated[AIClient, Depends(get_ai_client)]
