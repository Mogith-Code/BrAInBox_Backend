"""Every error uses {"error": {"code", "message"}}."""

from api.core.config import ApiSettings


async def test_unknown_route_uses_error_format(anon_client):
    response = await anon_client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "NOT_FOUND", "message": "Not Found"}}


async def test_missing_token_uses_error_format(anon_client):
    response = await anon_client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json() == {"error": {"code": "UNAUTHORIZED", "message": "Missing bearer token"}}


async def test_validation_error_uses_error_format(admin_client):
    response = await admin_client.get("/api/v1/admin/questions/not-a-uuid")
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"][0]["field"] == "path.question_id"


def test_admin_origins_are_added_to_cors():
    from api.core.config import ApiSettings

    settings = ApiSettings(ADMIN_ORIGINS="https://admin.brainbox.lk, https://staging.brainbox.lk")
    assert settings.cors_exact_origins() == [
        "https://admin.brainbox.lk",
        "https://staging.brainbox.lk",
    ]
    assert settings.cors_origin_regex() is not None  # localhost:* is still allowed


async def test_cors_preflight_allows_authorization_from_flutter_web(anon_client):
    response = await anon_client.options(
        "/api/v1/admin/users",
        headers={
            "Origin": "http://localhost:53124",
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:53124"
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


def test_cors_wildcard_ports_for_flutter_web():
    settings = ApiSettings(CORS_ORIGINS="http://localhost:*,https://admin.brainbox.lk")
    assert settings.cors_exact_origins() == ["https://admin.brainbox.lk"]
    import re

    pattern = re.compile(settings.cors_origin_regex() or "")
    assert pattern.match("http://localhost:5173")
    assert pattern.match("http://localhost:49152")
    assert not pattern.match("http://evil.example.com")


# --------------------------------------------------------------------------- framework errors


def _app_with_failing_routes():  # type: ignore[no-untyped-def]
    """A tiny app with the real error handlers and routes that raise on purpose."""
    from fastapi import FastAPI, HTTPException

    from api.core.errors import register_error_handlers

    app = FastAPI()
    register_error_handlers(app)

    @app.get("/teapot")
    async def teapot() -> None:
        raise HTTPException(status_code=418, detail="I'm a teapot")

    @app.get("/gone")
    async def gone() -> None:
        raise HTTPException(status_code=404, detail="Gone fishing")

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internals: password=hunter2")

    return app


def _client_for(app):  # type: ignore[no-untyped-def]
    from httpx import ASGITransport, AsyncClient

    # raise_app_exceptions=False: get the 500 response instead of the exception, like a real client.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_unknown_route_outside_api_prefix_uses_error_format(anon_client):
    response = await anon_client.get("/no-such-page")
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "NOT_FOUND", "message": "Not Found"}}


async def test_wrong_method_uses_error_format(anon_client):
    response = await anon_client.delete("/api/v1/health")
    assert response.status_code == 405
    assert response.json() == {
        "error": {"code": "METHOD_NOT_ALLOWED", "message": "Method Not Allowed"}
    }
    assert "GET" in response.headers["allow"]


async def test_learn_routes_keep_their_extra_keys_on_404(anon_client):
    response = await anon_client.get("/api/v1/learn/does-not-exist/at-all")
    assert response.status_code == 404
    body = response.json()
    assert body["error"] == {"code": "NOT_FOUND", "message": "Not Found"}
    assert body["code"] == "NOT_FOUND"
    assert body["detail"] == "Not Found"


async def test_plain_http_exception_with_unnamed_status_becomes_http_status_code():
    async with _client_for(_app_with_failing_routes()) as c:
        response = await c.get("/teapot")
    assert response.status_code == 418
    assert response.json() == {"error": {"code": "HTTP_418", "message": "I'm a teapot"}}


async def test_plain_http_exception_with_named_status_keeps_name_and_detail():
    async with _client_for(_app_with_failing_routes()) as c:
        response = await c.get("/gone")
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "NOT_FOUND", "message": "Gone fishing"}}


async def test_unexpected_exception_is_500_without_traceback(caplog):
    async with _client_for(_app_with_failing_routes()) as c:
        response = await c.get("/boom")
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "INTERNAL_ERROR", "message": "Something went wrong"}
    }
    assert "hunter2" not in response.text
    assert "Traceback" not in response.text
    # ...but the traceback IS in the server log.
    logged = [r for r in caplog.records if r.levelname == "ERROR" and r.exc_info]
    assert logged, "the unhandled error should be logged with its traceback"
    assert "GET /boom" in logged[0].getMessage()
    assert isinstance(logged[0].exc_info[1], RuntimeError)
