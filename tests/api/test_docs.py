"""Branded /docs and /redoc, and every module visible in OpenAPI."""

EXPECTED_TAGS = {
    "Health",
    "Auth",
    "Profiles",
    "Home",
    "Syllabus",
    "Content",
    "Visuals",
    "Questions",
    "Quizzes",
    "Diagnostic",
    "Exams",
    "Quality",
    "Evaluation",
    "Knowledge base",
    "Performance",
    "Recommendations",
    "Community",
    "Jobs",
    "Admin: content",
    "Admin: RAG documents",
    "Admin: questions",
    "Admin: knowledge base",
    "Admin: syllabus",
    "Admin: analytics",
    "Admin: moderation",
    "Admin: users",
}


async def test_swagger_docs_are_branded(anon_client):
    response = await anon_client.get("/docs")
    assert response.status_code == 200
    assert "BrAInBox API – Docs" in response.text
    assert "/static/brand/favicon_32.png" in response.text


async def test_redoc_is_branded(anon_client):
    response = await anon_client.get("/redoc")
    assert response.status_code == 200
    assert "BrAInBox API – Docs" in response.text
    assert "/static/brand/favicon_32.png" in response.text


async def test_openapi_has_logo_and_tagline(anon_client):
    info = (await anon_client.get("/openapi.json")).json()["info"]
    assert info["title"] == "BrAInBox API"
    assert "Study smarter. Fix what matters." in info["description"]
    assert info["x-logo"] == {
        "url": "/static/brand/logo_horizontal_1200.png",
        "altText": "BrAInBox",
    }


async def test_brand_files_are_served(anon_client):
    for name in ["favicon_32.png", "favicon_192.png", "logo_horizontal_1200.png"]:
        response = await anon_client.get(f"/static/brand/{name}")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"


async def test_every_module_is_listed_in_docs(anon_client):
    schema = (await anon_client.get("/openapi.json")).json()
    tags = {tag for path in schema["paths"].values() for op in path.values() for tag in op["tags"]}
    assert EXPECTED_TAGS <= tags
    assert all(path.startswith("/api/v1/") for path in schema["paths"])
