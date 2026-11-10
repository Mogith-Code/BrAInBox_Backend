"""Dev login for /docs (api/core/security.py): works only when switched on, in dev, from this
computer. Everywhere else "dev-token" / "dev-admin" are just invalid tokens."""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from starlette.requests import Request

from api.core.config import get_settings
from api.core.security import dev_login_allowed
from api.main import create_app
from shared.db.models import User


def request_from(host: str) -> Request:
    return Request({"type": "http", "client": (host, 50000), "headers": []})


@pytest.fixture
def dev_login_on(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "DEV_LOGIN_ENABLED", True)
    monkeypatch.setattr(settings, "ENVIRONMENT", "dev")


def client_from(host: str) -> AsyncClient:
    transport = ASGITransport(app=create_app(), client=(host, 50000))
    return AsyncClient(transport=transport, base_url="http://test")


# --------------------------------------------------------------------------- the rule


def test_off_by_default() -> None:
    assert get_settings().DEV_LOGIN_ENABLED is False
    assert dev_login_allowed(request_from("127.0.0.1")) is False


@pytest.mark.usefixtures("dev_login_on")
def test_only_from_this_computer() -> None:
    assert dev_login_allowed(request_from("127.0.0.1")) is True
    assert dev_login_allowed(request_from("::1")) is True
    assert dev_login_allowed(request_from("192.168.1.20")) is False  # another device on the network


@pytest.mark.parametrize("environment", ["test", "prod", "staging"])
def test_only_in_dev(monkeypatch: pytest.MonkeyPatch, environment: str) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "DEV_LOGIN_ENABLED", True)
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)
    assert dev_login_allowed(request_from("127.0.0.1")) is False


@pytest.mark.parametrize("environment", ["test", "prod"])
def test_api_refuses_to_start_with_it_outside_dev(
    monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "DEV_LOGIN_ENABLED", True)
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)
    with pytest.raises(RuntimeError, match="DEV_LOGIN_ENABLED"):
        create_app()


# --------------------------------------------------------------------------- requests


async def test_no_token_is_still_401_even_with_dev_login(dev_login_on: None) -> None:
    async with client_from("127.0.0.1") as c:
        response = await c.get("/api/v1/auth/me")
    assert response.status_code == 401  # no automatic login without a token


async def test_dev_token_is_refused_when_off() -> None:
    async with client_from("127.0.0.1") as c:
        response = await c.get("/api/v1/auth/me", headers={"Authorization": "Bearer dev-admin"})
    assert response.status_code in (401, 503)  # treated as a (bad) Firebase token


async def test_dev_token_is_refused_from_another_device(dev_login_on: None) -> None:
    async with client_from("192.168.1.20") as c:
        response = await c.get("/api/v1/auth/me", headers={"Authorization": "Bearer dev-admin"})
    assert response.status_code in (401, 503)


@pytest.mark.db
async def test_dev_tokens_log_in_test_users(dev_login_on: None, db_session) -> None:  # type: ignore[no-untyped-def]
    try:
        async with client_from("127.0.0.1") as c:
            # An admin-only route: the test admin gets in, the test student does not.
            admin = await c.get(
                "/api/v1/admin/moderation/status", headers={"Authorization": "Bearer dev-admin"}
            )
            student = await c.get(
                "/api/v1/admin/moderation/status", headers={"Authorization": "Bearer dev-token"}
            )
        assert admin.status_code == 200, admin.text
        assert student.status_code == 403, student.text
    finally:
        await db_session.execute(
            delete(User).where(User.firebase_uid.in_(["dev-student", "dev-admin"]))
        )
        await db_session.commit()
