"""Every error uses {"error": {"code", "message"}}."""

from api.core.config import ApiSettings


async def test_unknown_route_uses_error_format(anon_client):
    response = await anon_client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "NOT_FOUND", "message": "Not Found"}}


async def test_missing_token_uses_error_format(anon_client):
    response = await anon_client.get("/api/v1/auth/status")
    assert response.status_code == 401
    assert response.json() == {"error": {"code": "UNAUTHORIZED", "message": "Missing bearer token"}}


async def test_validation_error_uses_error_format(admin_client):
    response = await admin_client.post("/api/v1/admin/rag/documents/not-a-uuid/reindex")
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"][0]["field"] == "path.document_id"


def test_cors_wildcard_ports_for_flutter_web():
    settings = ApiSettings(CORS_ORIGINS="http://localhost:*,https://admin.brainbox.lk")
    assert settings.cors_exact_origins() == ["https://admin.brainbox.lk"]
    import re

    pattern = re.compile(settings.cors_origin_regex() or "")
    assert pattern.match("http://localhost:5173")
    assert pattern.match("http://localhost:49152")
    assert not pattern.match("http://evil.example.com")
