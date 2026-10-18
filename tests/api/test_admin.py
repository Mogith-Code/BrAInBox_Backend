"""Admin routes: placeholders exist and require the admin role."""

import pytest

ADMIN_AREAS = [
    ("content", "content_admin"),  # Samni
    ("rag", "rag_admin"),  # Samni
    ("questions", "questions_admin"),  # Udith
    ("knowledge", "knowledge_admin"),  # Keshomigha
    ("syllabus", "syllabus_admin"),  # Keshomigha
    ("analytics", "analytics_admin"),  # Keshomigha
    ("moderation", "moderation_admin"),  # Mogith
    ("users", "users_admin"),  # Mogith
]


@pytest.mark.parametrize(("prefix", "module"), ADMIN_AREAS)
async def test_admin_area_placeholder(admin_client, prefix, module):
    response = await admin_client.get(f"/api/v1/admin/{prefix}/status")
    assert response.status_code == 200
    assert response.json() == {"module": module, "status": "todo"}


@pytest.mark.parametrize(("prefix", "module"), ADMIN_AREAS)
async def test_admin_area_forbidden_for_students(client, prefix, module):
    response = await client.get(f"/api/v1/admin/{prefix}/status")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_admin_requires_login(anon_client):
    response = await anon_client.get("/api/v1/admin/users/status")
    assert response.status_code == 401


async def test_rag_documents_placeholders(admin_client):
    assert (await admin_client.get("/api/v1/admin/rag/documents")).status_code == 200
    upload = await admin_client.post(
        "/api/v1/admin/rag/documents",
        data={"title": "Sample", "source_type": "approved_note", "unit_number": "2"},
        files={"file": ("sample.txt", b"Active transport needs ATP.", "text/plain")},
    )
    assert upload.status_code == 200
    reindex = await admin_client.post(
        "/api/v1/admin/rag/documents/00000000-0000-0000-0000-000000000001/reindex"
    )
    assert reindex.status_code == 200
