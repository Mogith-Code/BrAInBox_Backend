"""Admin routes need a login and the admin role (checked once in admin/router.py)."""

import pytest

# One real GET route per admin area (owner in the comment).
ADMIN_ROUTES = [
    "/api/v1/admin/content",  # Samni
    "/api/v1/admin/rag/sources",  # Samni
    "/api/v1/admin/questions",  # Udith
    "/api/v1/admin/model-answers",  # Keshomigha
    "/api/v1/admin/syllabus/units",  # Keshomigha
    "/api/v1/admin/analytics/overview",  # Keshomigha
    "/api/v1/admin/moderation/reports",  # Mogith
    "/api/v1/admin/users",  # Mogith
]


@pytest.mark.parametrize("path", ADMIN_ROUTES)
async def test_admin_area_forbidden_for_students(client, path):
    response = await client.get(path)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize("path", ADMIN_ROUTES)
async def test_admin_area_requires_login(anon_client, path):
    assert (await anon_client.get(path)).status_code == 401


async def test_old_placeholder_routes_are_gone(admin_client):
    for path in ("/api/v1/admin/users/status", "/api/v1/admin/rag/documents"):
        assert (await admin_client.get(path)).status_code in (404, 405, 422)
