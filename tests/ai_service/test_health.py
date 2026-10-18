"""The AI service rejects requests without the service token."""


async def test_health_needs_service_token(ai_anon_client):
    response = await ai_anon_client.get("/health")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_SERVICE_TOKEN"


async def test_health_rejects_wrong_token(ai_anon_client):
    response = await ai_anon_client.get("/health", headers={"X-Service-Token": "wrong"})
    assert response.status_code == 401


async def test_health_with_token(ai_client):
    response = await ai_client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["fake_ai"] is True
    assert body["providers"] == {"llm": "fake-llm", "embedder": "fake-embedder"}


async def test_docs_are_open_and_branded(ai_anon_client):
    response = await ai_anon_client.get("/docs")
    assert response.status_code == 200
    assert "BrAInBox AI Service (internal) – Docs" in response.text
    assert "/static/brand/favicon_32.png" in response.text
    info = (await ai_anon_client.get("/openapi.json")).json()["info"]
    assert info["x-logo"]["url"] == "/static/brand/logo_horizontal_1200.png"
