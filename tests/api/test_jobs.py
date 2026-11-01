"""Tests for the jobs module (GET /jobs/{job_id}). Owner: shared.

End-to-end polling of a real job is tested with visuals (tests/api/test_visuals.py).
"""

import uuid

import pytest

from api.modules.jobs.service import BUSY_ERROR, GENERIC_ERROR, readable_error


async def test_job_requires_login(anon_client):
    response = await anon_client.get(f"/api/v1/jobs/{uuid.uuid4()}")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_job_id_must_be_a_uuid(client):
    response = await client.get("/api/v1/jobs/not-a-uuid")
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("NOT_BIOLOGY: I can only draw Biology visuals.", ("I can only draw Biology visuals.", "NOT_BIOLOGY")),
        ("AI_SERVICE_UNAVAILABLE: The AI service is not available right now", (BUSY_ERROR, "AI_SERVICE_UNAVAILABLE")),
        ("Traceback (most recent call last): KeyError 'kind'", (GENERIC_ERROR, None)),
        (None, (GENERIC_ERROR, None)),
    ],
)  # fmt: skip
def test_job_errors_are_readable(stored: str | None, expected: tuple[str, str | None]) -> None:
    assert readable_error(stored) == expected
